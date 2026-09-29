"""
Compare the app's retriever with a larger embedding model and hybrid rankers.

    # Needs eval/gold.csv (from run_eval.py --controls ...) and three ONNX exports,
    # each checked against the archive hash below before use:
    curl -sSLO https://chroma-onnx-models.s3.amazonaws.com/all-MiniLM-L6-v2/onnx.tar.gz
    curl -sSLO https://storage.googleapis.com/qdrant-fastembed/fast-bge-small-en-v1.5.tar.gz
    curl -sSLO https://storage.googleapis.com/qdrant-fastembed/fast-bge-base-en-v1.5.tar.gz
    uv run --with onnxruntime python scripts/compare_retrievers.py --models <dir>

<dir> holds the three archives. They are extracted next to themselves. Writes
eval/retriever_comparison.md (numbers only). See eval/README.md for the reading.
"""

import argparse
import hashlib
import os
import sys
import tarfile

import numpy as np
from scipy.stats import binomtest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(ROOT, "src"))

from evaluation import read_gold_csv, scores_from_rankings, tfidf_retriever  # noqa: E402
from mapper import (  # noqa: E402
    CROSSWALK_CANDIDATES,
    _chunk_words,
    _control_texts,
    load_scf_database,
)

EVAL_DIR = os.path.join(ROOT, "eval")
KS = (1, 3, 5, 10, 20, CROSSWALK_CANDIDATES)
BGE_QUERY = "Represent this sentence for searching relevant passages: "

# name: (archive, archive sha256, directory inside, onnx file, pooling, max tokens, query prefix)
MODELS = {
    "all-MiniLM-L6-v2 (app)": (
        "onnx.tar.gz",
        "913d7300ceae3b2dbc2c50d1de4baacab4be7b9380491c27fab7418616a16ec3",  # pragma: allowlist secret (a file hash)
        "onnx",
        "model.onnx",
        "mean",
        256,
        "",
    ),
    "bge-small-en-v1.5": (
        "fast-bge-small-en-v1.5.tar.gz",
        "3858004b3822f64f940280874b8f2d2dc25b34a4f3eb3cdf617bdceeb21ed9ed",  # pragma: allowlist secret (a file hash)
        "fast-bge-small-en-v1.5",
        "model_optimized.onnx",
        "cls",
        512,
        BGE_QUERY,
    ),
    "bge-base-en-v1.5": (
        "fast-bge-base-en-v1.5.tar.gz",
        "b2e829f86bb0933e7d7fabce2d881f718464880c22658d189a2f70de4527d991",  # pragma: allowlist secret (a file hash)
        "fast-bge-base-en-v1.5",
        "model_optimized.onnx",
        "cls",
        512,
        BGE_QUERY,
    ),
}
APP = "all-MiniLM-L6-v2 (app)"


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _encoder(model_dir: str, onnx_file: str, pooling: str, max_length: int):
    import onnxruntime as ort
    from tokenizers import Tokenizer

    session = ort.InferenceSession(
        os.path.join(model_dir, onnx_file), providers=["CPUExecutionProvider"]
    )
    tokenizer = Tokenizer.from_file(os.path.join(model_dir, "tokenizer.json"))
    tokenizer.no_padding()
    tokenizer.enable_truncation(max_length=max_length)
    names = {i.name for i in session.get_inputs()}

    def encode(texts: list[str]) -> np.ndarray:
        out = []
        for start in range(0, len(texts), 32):
            encodings = tokenizer.encode_batch(texts[start : start + 32])
            width = max(len(e.ids) for e in encodings)
            ids = np.zeros((len(encodings), width), dtype=np.int64)
            mask = np.zeros_like(ids)
            for row, e in enumerate(encodings):
                ids[row, : len(e.ids)] = e.ids
                mask[row, : len(e.ids)] = 1
            feed = {"input_ids": ids, "attention_mask": mask}
            if "token_type_ids" in names:
                feed["token_type_ids"] = np.zeros_like(ids)
            hidden = np.asarray(session.run(None, feed)[0])
            if pooling == "cls":
                vectors = hidden[:, 0]
            else:
                vectors = (hidden * mask[..., None]).sum(1) / mask.sum(1, keepdims=True)
            out.append(vectors / np.linalg.norm(vectors, axis=1, keepdims=True))
        return np.concatenate(out)

    return encode


def _rrf(a: list[str], b: list[str], k: int = 60) -> list[str]:
    """Reciprocal-rank fusion with the usual k = 60 and equal weights."""
    score: dict[str, float] = {}
    for ranking in (a, b):
        for rank, cid in enumerate(ranking):
            score[cid] = score.get(cid, 0.0) + 1.0 / (k + rank + 1)
    return sorted(score, key=lambda cid: -score[cid])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--models", required=True, help="directory with the archives")
    parser.add_argument("--gold", default=os.path.join(EVAL_DIR, "gold.csv"))
    args = parser.parse_args(argv)

    cases = read_gold_csv(args.gold)
    scf_data = load_scf_database()
    if not scf_data:
        print("SCF database not found. Download it from the app sidebar first.")
        return 1
    ids = [c["control_id"] for c in scf_data]
    texts = _control_texts(scf_data)

    rankings: dict[str, list[list[str]]] = {}
    for name, (
        archive,
        sha,
        inner,
        onnx_file,
        pooling,
        max_len,
        prefix,
    ) in MODELS.items():
        path = os.path.join(args.models, archive)
        if _sha256(path) != sha:
            raise SystemExit(f"{archive}: sha256 does not match the pinned hash.")
        with tarfile.open(path) as tar:
            tar.extractall(args.models, filter="data")
        encode = _encoder(os.path.join(args.models, inner), onnx_file, pooling, max_len)
        corpus = encode(texts)
        ranked = []
        for case in cases:
            # Same scheme as mapper._semantic_filter: best chunk per control.
            query = encode([prefix + chunk for chunk in _chunk_words(case.text)])
            similarities = (query @ corpus.T).max(axis=0)
            ranked.append([ids[i] for i in np.argsort(-similarities)])
        rankings[name] = ranked
        print(f"Ranked {len(cases)} cases with {name}")

    lexical = tfidf_retriever(ids, texts)
    rankings["TF-IDF"] = [lexical(case.text, len(ids)) for case in cases]
    rankings["MiniLM + TF-IDF (RRF)"] = [
        _rrf(a, b) for a, b in zip(rankings[APP], rankings["TF-IDF"])
    ]
    rankings["bge-base + TF-IDF (RRF)"] = [
        _rrf(a, b) for a, b in zip(rankings["bge-base-en-v1.5"], rankings["TF-IDF"])
    ]
    rankings["MiniLM + bge-base (RRF)"] = [
        _rrf(a, b) for a, b in zip(rankings[APP], rankings["bge-base-en-v1.5"])
    ]

    header = "| Retriever | " + " | ".join(f"Hit @{k}" for k in KS)
    header += f" | Recall @{KS[-1]} | MRR @{KS[-1]} |"
    lines = [
        f"Cases: {len(cases)}; SCF controls ranked: {len(ids)}",
        "",
        header,
        "|---|" + "---:|" * (len(KS) + 2),
    ]
    for name, ranked in rankings.items():
        scores = scores_from_rankings(cases, ranked, KS)
        cells = [f"{s.hit_rate:.1%}" for s in scores]
        cells += [f"{scores[-1].mean_recall:.1%}", f"{scores[-1].mrr:.3f}"]
        lines.append(f"| {name} | " + " | ".join(cells) + " |")

    lines += [
        "",
        f"Paired against {APP}: cases only this retriever hits / cases only the app's "
        "hits, exact McNemar p.",
        "",
        "| Retriever | @10 | p @10 | @50 | p @50 |",
        "|---|---:|---:|---:|---:|",
    ]
    for name, ranked in rankings.items():
        if name == APP:
            continue
        cells = []
        for k in (10, KS[-1]):
            ours = [bool(c.gold & set(r[:k])) for c, r in zip(cases, ranked)]
            app = [bool(c.gold & set(r[:k])) for c, r in zip(cases, rankings[APP])]
            gained = sum(o and not a for o, a in zip(ours, app))
            lost = sum(a and not o for o, a in zip(ours, app))
            p = binomtest(gained, gained + lost).pvalue if gained + lost else 1.0
            cells += [f"+{gained} / −{lost}", f"{p:.3f}"]
        lines.append(f"| {name} | " + " | ".join(cells) + " |")

    out = os.path.join(EVAL_DIR, "retriever_comparison.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"Saved to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
