"""
An ONNX stand-in for SentenceTransformer("all-MiniLM-L6-v2").encode, for the
evaluation only.

The app loads the PyTorch model from Hugging Face. Where Hugging Face is out of
reach, `scripts/run_eval.py --onnx-model DIR` uses the ONNX export of the same
model that chromadb downloads and pins by SHA-256 (CHROMA_ONNX_URL,
CHROMA_ONNX_SHA256 below), and reproduces what sentence-transformers does for
this model: BERT word-piece tokenization truncated at 256 tokens, mean pooling
over the attention mask, L2 normalization.

onnxruntime is not a project dependency; it is imported only when a model is
loaded (`uv run --with onnxruntime ...`). The pooling code is plain numpy and
is unit-tested with a fake session.
"""

import hashlib
import importlib
import os
from collections.abc import Sequence
from typing import Any

import numpy as np
from tokenizers import Tokenizer

# The ONNX export chromadb's ONNXMiniLM_L6_V2 embedding function downloads, and
# the SHA-256 chromadb pins for it (chromadb 1.5.9,
# chromadb/utils/embedding_functions/onnx_mini_lm_l6_v2.py, _MODEL_SHA256).
CHROMA_ONNX_URL = (
    "https://chroma-onnx-models.s3.amazonaws.com/all-MiniLM-L6-v2/onnx.tar.gz"
)
CHROMA_ONNX_SHA256 = "913d7300ceae3b2dbc2c50d1de4baacab4be7b9380491c27fab7418616a16ec3"  # pragma: allowlist secret (a file hash)

# sentence-transformers' max_seq_length for all-MiniLM-L6-v2. The tokenizer.json
# shipped with the model says 128; sentence-transformers overrides it with 256.
MAX_SEQ_LENGTH = 256


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def mean_pool_normalize(hidden: np.ndarray, attention_mask: np.ndarray) -> np.ndarray:
    """Mean of the token vectors where attention_mask is 1, then L2-normalized."""
    mask = attention_mask[..., None].astype(hidden.dtype)
    summed = (hidden * mask).sum(axis=1)
    pooled = summed / np.clip(mask.sum(axis=1), 1e-9, None)
    norms = np.linalg.norm(pooled, axis=1, keepdims=True)
    return pooled / np.clip(norms, 1e-12, None)


class OnnxSentenceEncoder:
    """
    The subset of SentenceTransformer.encode that src/mapper.py uses:
    `encode(texts, convert_to_numpy=True, show_progress_bar=False)`.
    """

    def __init__(
        self,
        session: Any,
        tokenizer: Tokenizer,
        max_length: int = MAX_SEQ_LENGTH,
        batch_size: int = 32,
    ):
        self.session = session
        self.tokenizer = tokenizer
        # Replace the tokenizer file's own settings (truncate and pad to 128)
        # with sentence-transformers': truncate at max_length, pad per batch.
        self.tokenizer.no_padding()
        self.tokenizer.enable_truncation(max_length=max_length)
        self.batch_size = batch_size
        self._input_names = {i.name for i in session.get_inputs()}

    def encode(
        self, sentences: str | Sequence[str], batch_size: int | None = None, **_: Any
    ) -> np.ndarray:
        single = isinstance(sentences, str)
        texts = [sentences] if single else list(sentences)
        size = batch_size or self.batch_size
        out = []
        for start in range(0, len(texts), size):
            encodings = self.tokenizer.encode_batch(texts[start : start + size])
            width = max(len(e.ids) for e in encodings)
            ids = np.zeros((len(encodings), width), dtype=np.int64)
            mask = np.zeros_like(ids)
            for row, e in enumerate(encodings):
                ids[row, : len(e.ids)] = e.ids
                mask[row, : len(e.ids)] = 1
            feed = {"input_ids": ids, "attention_mask": mask}
            if "token_type_ids" in self._input_names:
                feed["token_type_ids"] = np.zeros_like(ids)
            hidden = self.session.run(None, feed)[0]
            out.append(mean_pool_normalize(np.asarray(hidden), mask))
        embeddings = (
            np.concatenate(out).astype(np.float32)
            if out
            else np.zeros((0, 0), dtype=np.float32)
        )
        return embeddings[0] if single else embeddings


def load_onnx_encoder(model_dir: str) -> OnnxSentenceEncoder:
    """Load model.onnx and tokenizer.json from an extracted export (needs onnxruntime)."""
    ort = importlib.import_module("onnxruntime")
    session = ort.InferenceSession(
        os.path.join(model_dir, "model.onnx"), providers=["CPUExecutionProvider"]
    )
    tokenizer = Tokenizer.from_file(os.path.join(model_dir, "tokenizer.json"))
    return OnnxSentenceEncoder(session, tokenizer)
