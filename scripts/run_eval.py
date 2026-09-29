"""
Build the Security Hub -> NIST 800-53 -> SCF gold set and score the pipeline.

    # 1. Security Hub controls with their NIST 800-53 mappings, either from
    #    the API (read-only call; the NIST SP 800-53 rev 5 standard or AWS FSBP)
    aws securityhub describe-standards-controls \
        --standards-subscription-arn <arn> > data/standards_controls.json
    #    or from the public user guide sources (see import_awsdocs_controls.py)
    uv run python scripts/import_awsdocs_controls.py --repo <clone>

    # 2. Build the gold set and score retrieval (no OpenRouter key needed)
    uv run python scripts/run_eval.py --controls data/awsdocs_controls.json

    # 2b. Same, with the ONNX export of the embedding model instead of the
    #     Hugging Face download (see src/onnx_encoder.py)
    uv run --with onnxruntime python scripts/run_eval.py \
        --controls data/awsdocs_controls.json --onnx-model <extracted onnx dir>

    # 3. Also score the model step (one OpenRouter call per case)
    uv run python scripts/run_eval.py --gold eval/gold.csv --llm

    # 3b. Same, on another OpenRouter model than the app's default
    #     (the same as setting OPENROUTER_MODEL for this run)
    uv run python scripts/run_eval.py \
        --gold eval/gold.csv --llm --openrouter-model <model id>

Needs the SCF database in data/ and, without --onnx-model, network access to
Hugging Face for the embedding model. Writes eval/results.md and
eval/per_case_retrieval.csv (IDs and numbers only), and with --llm
eval/per_case_model.csv; eval/gold.csv holds AWS
text and is git-ignored. See eval/README.md for what the numbers mean.
"""

import argparse
import json
import os
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(ROOT, "src"))

from evaluation import (  # noqa: E402
    SMALL_GOLD,
    Suggestion,
    build_gold_set,
    comparison_markdown,
    gold_set_stats,
    nist_800_53_column,
    random_baseline,
    read_gold_csv,
    results_markdown,
    score_model,
    scores_from_rankings,
    tfidf_retriever,
    write_gold_csv,
    write_per_case_csv,
    write_per_case_model_csv,
)
from demo import demo_mode_enabled  # noqa: E402
from fetch_scf import read_scf_release  # noqa: E402
import mapper  # noqa: E402
from mapper import (  # noqa: E402
    CROSSWALK_CANDIDATES,
    DEFAULT_OPENROUTER_MODEL,
    _control_texts,
    _semantic_filter,
    load_scf_database,
    map_text_to_scf,
)

EVAL_DIR = os.path.join(ROOT, "eval")
DEFAULT_KS = (1, 3, 5, 10, 20, CROSSWALK_CANDIDATES)


def _suggestion(result) -> Suggestion:
    """The suggested IDs and the IDs validation rejected, from a MappingResult."""
    if result is None:
        return Suggestion([])
    return Suggestion(
        [m.control_id for m in result.mappings], list(result.rejected_control_ids)
    )


def use_onnx_model(model_dir: str, allow_unverified: bool = False) -> str:
    """
    Swap the embedding model for the ONNX export in model_dir and keep its
    embeddings in their own cache file. Returns a label for the report.

    Refuses a model.onnx whose hash differs from the one the published results
    used, unless allow_unverified is set.
    """
    from onnx_encoder import MODEL_ONNX_SHA256, load_onnx_encoder, sha256_file

    digest = sha256_file(os.path.join(model_dir, "model.onnx"))
    if digest != MODEL_ONNX_SHA256 and not allow_unverified:
        raise SystemExit(
            f"model.onnx sha256 {digest} is not the pinned {MODEL_ONNX_SHA256}; "
            "pass --allow-unverified-onnx to score it anyway."
        )
    encoder = load_onnx_encoder(model_dir)
    mapper._get_embedding_model = lambda: encoder
    mapper.EMBEDDINGS_CACHE_FILE = os.path.join(
        mapper.DATA_DIR, "scf_embeddings_onnx.npz"
    )
    mapper._embeddings_memo.clear()
    return f"all-MiniLM-L6-v2, ONNX export (model.onnx sha256 {digest})"


def _suggest(text: str) -> Suggestion:
    """The full pipeline on one input, through the app's own client and retry."""
    return _suggestion(map_text_to_scf(text, top_k=3))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--controls", help="describe-standards-controls JSON output")
    source.add_argument("--gold", help="an existing gold CSV")
    parser.add_argument("--column", help="SCF crosswalk column for NIST 800-53")
    parser.add_argument("--llm", action="store_true", help="also score the model step")
    parser.add_argument("--limit", type=int, help="score only the first N cases")
    parser.add_argument(
        "--onnx-model", help="directory with model.onnx and tokenizer.json"
    )
    parser.add_argument(
        "--allow-unverified-onnx",
        action="store_true",
        help="score a model.onnx whose hash is not the pinned one",
    )
    parser.add_argument(
        "--openrouter-model",
        help="score the model step on this OpenRouter model instead of the "
        "app's default (sets OPENROUTER_MODEL for this run)",
    )
    args = parser.parse_args(argv)

    if demo_mode_enabled():
        # The demo catalog and canned model would produce meaningless numbers
        # labeled with the real SCF release and model name.
        print(
            "DEMO_MODE is on; the evaluation needs the real SCF data. Unset DEMO_MODE."
        )
        return 1

    scf_data = load_scf_database()
    if not scf_data:
        print("SCF database not found. Download it from the app sidebar first.")
        return 1
    column = nist_800_53_column(scf_data, args.column)

    stats = None
    if args.controls:
        if column is None and args.column:
            print(f"The SCF data has no crosswalk column named {args.column!r}.")
            return 1
        if column is None:
            print("No NIST 800-53 column in the SCF data; pass --column.")
            return 1
        with open(args.controls, encoding="utf-8") as f:
            data = json.load(f)
        controls = (
            data.get("StandardsControls", data) if isinstance(data, dict) else data
        )
        cases = build_gold_set(controls, scf_data, column)
        stats = gold_set_stats(controls, cases)
        os.makedirs(EVAL_DIR, exist_ok=True)
        gold_path = os.path.join(EVAL_DIR, "gold.csv")
        write_gold_csv(cases, gold_path)
        print(f"Wrote {len(cases)} cases to {gold_path}")
    else:
        cases = read_gold_csv(args.gold)

    if args.limit:
        cases = cases[: args.limit]

    embedder = "all-MiniLM-L6-v2 (sentence-transformers)"
    if args.onnx_model:
        embedder = use_onnx_model(args.onnx_model, args.allow_unverified_onnx)

    ks = DEFAULT_KS
    k_max = max(ks)
    ids = [c["control_id"] for c in scf_data]
    lexical = tfidf_retriever(ids, _control_texts(scf_data))
    rankings = {
        "embedding": [
            [c["control_id"] for c in _semantic_filter(case.text, scf_data, k_max)]
            for case in cases
        ],
        "tfidf": [lexical(case.text, k_max) for case in cases],
    }
    retrieval = scores_from_rankings(cases, rankings["embedding"], ks)

    model = None
    llm_name = None
    if args.llm:
        if not os.environ.get("OPENROUTER_API_KEY"):
            print("OPENROUTER_API_KEY is not set; skipping the model step.")
        else:
            if args.openrouter_model:
                os.environ["OPENROUTER_MODEL"] = args.openrouter_model
            model_id = os.environ.get("OPENROUTER_MODEL", DEFAULT_OPENROUTER_MODEL)
            llm_name = f"{model_id} (OpenRouter)"
            model = score_model(cases, _suggest)
            failures = Counter(m.error for m in model.per_case if m.failed)
            for error, count in failures.most_common():
                print(f"Model call failed for {count} case(s): {error}")

    table = results_markdown(retrieval, model, read_scf_release(), column, llm_name)
    sections = [table, f"Embedding model: {embedder}; SCF controls ranked: {len(ids)}"]
    if stats is not None:
        sections.append(
            "## Gold set\n\n"
            f"Security Hub controls read: {stats.controls}; dropped without a NIST "
            f"800-53 rev 5 requirement: {stats.no_nist}; dropped because SCF maps "
            f"none of their 800-53 requirements: {stats.no_scf}; cases: "
            f"{stats.cases}. Gold controls per case: median {stats.median_gold:g}, "
            f"max {stats.max_gold}; cases with at most {SMALL_GOLD}: "
            f"{stats.small_cases}."
        )
    small = [i for i, c in enumerate(cases) if len(c.gold) <= SMALL_GOLD]
    for title, subset in [
        ("All cases", list(range(len(cases)))),
        (f"Cases with at most {SMALL_GOLD} gold controls", small),
    ]:
        sub_cases = [cases[i] for i in subset]
        methods = {
            name: scores_from_rankings(sub_cases, [ranked[i] for i in subset], ks)
            for name, ranked in rankings.items()
        }
        methods["random (expected)"] = random_baseline(sub_cases, len(ids), ks)
        sections.append(
            f"## {title} ({len(sub_cases)})\n\n" + comparison_markdown(methods)
        )
    report = "\n\n".join(s.rstrip("\n") for s in sections) + "\n"

    os.makedirs(EVAL_DIR, exist_ok=True)
    out = os.path.join(EVAL_DIR, "results.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write(report)
    per_case = os.path.join(EVAL_DIR, "per_case_retrieval.csv")
    write_per_case_csv(per_case, cases, rankings, len(ids), k_max)
    saved = [out, per_case]
    if model is not None:
        per_case_model = os.path.join(EVAL_DIR, "per_case_model.csv")
        write_per_case_model_csv(per_case_model, model)
        saved.append(per_case_model)
    print(report)
    print("Saved to " + ", ".join(saved))
    return 0


if __name__ == "__main__":
    sys.exit(main())
