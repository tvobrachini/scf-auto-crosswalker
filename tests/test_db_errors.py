"""A corrupt SCF database is reported as such, and a cache write failure is not fatal."""

import numpy as np
import pytest

import mapper


@pytest.fixture(autouse=True)
def _no_demo(monkeypatch):
    monkeypatch.setattr(mapper, "demo_mode_enabled", lambda: False)
    mapper.clear_scf_cache()
    yield
    mapper.clear_scf_cache()


def test_missing_database_message(tmp_path, monkeypatch):
    monkeypatch.setattr(mapper, "PARSED_JSON_FILE", str(tmp_path / "nope.json"))
    assert mapper.load_scf_database() == []
    assert "not found" in mapper.scf_database_problem()


def test_corrupt_database_is_not_reported_as_missing(tmp_path, monkeypatch):
    bad = tmp_path / "scf_parsed.json"
    bad.write_text("{not json")
    monkeypatch.setattr(mapper, "PARSED_JSON_FILE", str(bad))
    assert mapper.load_scf_database() == []
    message = mapper.scf_database_problem()
    assert "cannot be read" in message and "not found" not in message


def test_embeddings_cache_write_failure_is_not_fatal(tmp_path, monkeypatch):
    class Model:
        def encode(self, texts, **kwargs):
            return np.ones((len(texts), 3), dtype=np.float32)

    def boom(*args):
        raise OSError("read-only file system")

    monkeypatch.setattr(mapper, "EMBEDDINGS_CACHE_FILE", str(tmp_path / "e.npz"))
    monkeypatch.setattr(mapper, "_get_embedding_model", lambda: Model())
    monkeypatch.setattr(mapper, "_write_embeddings_cache", boom)
    mapper._embeddings_memo.clear()
    data = [{"control_id": "GOV-01", "domain": "G", "description": "Run a program."}]
    assert mapper._build_or_load_embeddings(data).shape == (1, 3)
