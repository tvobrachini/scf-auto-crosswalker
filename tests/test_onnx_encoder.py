"""The ONNX encoder's tokenization, pooling and normalization, with a fake session."""

import hashlib
from types import SimpleNamespace

import numpy as np
import pytest
from tokenizers import Tokenizer
from tokenizers.models import WordLevel
from tokenizers.pre_tokenizers import Whitespace
from tokenizers.processors import TemplateProcessing

import onnx_encoder
from onnx_encoder import OnnxSentenceEncoder, mean_pool_normalize, sha256_file

WORDS = ["[PAD]", "[UNK]", "[CLS]", "[SEP]", "encrypt", "data", "transit", "mfa"]


def make_tokenizer() -> Tokenizer:
    tok = Tokenizer(WordLevel({w: i for i, w in enumerate(WORDS)}, unk_token="[UNK]"))
    tok.pre_tokenizer = Whitespace()
    tok.post_processor = TemplateProcessing(
        single="[CLS] $A [SEP]", special_tokens=[("[CLS]", 2), ("[SEP]", 3)]
    )
    # Like the real tokenizer.json: truncate and pad to a fixed 128.
    tok.enable_truncation(max_length=128)
    tok.enable_padding(length=128)
    return tok


class FakeSession:
    """Token vector = a fixed row per token ID; records what it was fed."""

    def __init__(self, with_token_types=True):
        rng = np.random.default_rng(0)
        self.table = rng.normal(size=(len(WORDS), 4)).astype(np.float32)
        names = ["input_ids", "attention_mask"]
        if with_token_types:
            names.append("token_type_ids")
        self.inputs = [SimpleNamespace(name=n) for n in names]
        self.feeds = []

    def get_inputs(self):
        return self.inputs

    def run(self, _outputs, feed):
        self.feeds.append(feed)
        return [self.table[feed["input_ids"]]]


def expected(session, tokens):
    ids = [2] + [WORDS.index(t) for t in tokens] + [3]
    v = session.table[ids].mean(axis=0)
    return v / np.linalg.norm(v)


def test_mean_pool_ignores_padding_and_normalizes():
    hidden = np.array([[[1.0, 0.0], [3.0, 4.0], [100.0, 100.0]]])
    mask = np.array([[1, 1, 0]])
    out = mean_pool_normalize(hidden, mask)
    assert out[0] == pytest.approx(np.array([2.0, 2.0]) / np.sqrt(8))


def test_encode_matches_per_text_mean_pooling_in_a_padded_batch():
    session = FakeSession()
    enc = OnnxSentenceEncoder(session, make_tokenizer())
    out = enc.encode(["encrypt data in transit", "mfa"])
    assert out.shape == (2, 4) and out.dtype == np.float32
    assert out[0] == pytest.approx(
        expected(session, ["encrypt", "data", "[UNK]", "transit"]), abs=1e-6
    )
    assert out[1] == pytest.approx(expected(session, ["mfa"]), abs=1e-6)
    feed = session.feeds[0]
    assert feed["input_ids"].shape == (2, 6)  # padded to the longest, not to 128
    assert feed["attention_mask"][1].tolist() == [1, 1, 1, 0, 0, 0]
    assert feed["token_type_ids"].sum() == 0
    assert np.linalg.norm(out, axis=1) == pytest.approx([1.0, 1.0])


def test_encode_single_string_and_batches():
    session = FakeSession(with_token_types=False)
    enc = OnnxSentenceEncoder(session, make_tokenizer(), batch_size=1)
    one = enc.encode("mfa")
    assert one.shape == (4,)
    many = enc.encode(["mfa", "data", "encrypt"], convert_to_numpy=True)
    assert len(session.feeds) == 4  # one call per batch of one
    assert "token_type_ids" not in session.feeds[0]
    assert many[0] == pytest.approx(one)
    assert enc.encode([]).shape == (0, 0)


def test_encode_truncates_at_max_length_not_the_tokenizer_file_setting():
    session = FakeSession()
    enc = OnnxSentenceEncoder(session, make_tokenizer(), max_length=256)
    enc.encode(" ".join(["data"] * 400))
    assert session.feeds[0]["input_ids"].shape == (1, 256)
    short = OnnxSentenceEncoder(FakeSession(), make_tokenizer(), max_length=5)
    short.encode("encrypt data transit mfa")
    assert short.session.feeds[0]["input_ids"][0].tolist() == [2, 4, 5, 6, 3]


def test_sha256_file(tmp_path):
    path = tmp_path / "f.bin"
    path.write_bytes(b"abc" * 1000)
    assert sha256_file(str(path)) == hashlib.sha256(b"abc" * 1000).hexdigest()


def test_load_onnx_encoder_uses_onnxruntime_lazily(monkeypatch, tmp_path):
    make_tokenizer().save(str(tmp_path / "tokenizer.json"))
    created = []

    def inference_session(path, providers):
        created.append((path, providers))
        return FakeSession()

    fake_ort = SimpleNamespace(InferenceSession=inference_session)
    monkeypatch.setattr(onnx_encoder.importlib, "import_module", lambda name: fake_ort)
    enc = onnx_encoder.load_onnx_encoder(str(tmp_path))
    assert created == [(str(tmp_path / "model.onnx"), ["CPUExecutionProvider"])]
    assert enc.encode("mfa").shape == (4,)
