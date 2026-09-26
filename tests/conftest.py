"""Shared fakes. Nothing here touches the network, Hugging Face or Groq."""

import numpy as np
import pytest

SCF_SAMPLE = [
    {
        "control_id": "CRY-01",
        "domain": "Cryptographic Protections",
        "description": "Mechanisms exist to use encryption to protect data.",
        "weight": 10,
        "erl": "E-CRY-01",
        "question": "Does the organization use encryption?",
        "regulations": {"AICPA SOC 2 (2017)": "CC6.1", "GDPR": "Art 32"},
    },
    {
        "control_id": "CRY-03",
        "domain": "Cryptographic Protections",
        "description": "Mechanisms exist to encrypt data in transit.",
        "weight": 8,
        "erl": "",
        "question": "",
        "regulations": {"PCI DSS v4.0": "4.2"},
    },
    {
        "control_id": "IAC-06",
        "domain": "Identification & Authentication",
        "description": "Mechanisms exist to enforce multi-factor authentication.",
        "weight": 9,
        "erl": "",
        "question": "",
        "regulations": {"AICPA SOC 2 (2017)": "CC6.1", "ISO 27001 v2022": "8.5"},
    },
    {
        "control_id": "GOV-01",
        "domain": "Cybersecurity & Data Protection Governance",
        "description": "Mechanisms exist to run a security governance program.",
        "weight": 10,
        "erl": "",
        "question": "",
        "regulations": {"ISO 27001 v2013": "5.1", "ISO 27001 v2022": "5.1"},
    },
]

# A tiny bag-of-words "embedding" so retrieval behaves predictably.
_VOCAB = [
    "encrypt",
    "transit",
    "authentication",
    "governance",
    "https",
    "mfa",
    "program",
]


class FakeEmbeddingModel:
    def __init__(self):
        self.encode_calls: list[list[str]] = []

    def encode(self, texts, **kwargs):
        self.encode_calls.append(list(texts))
        rows = []
        for t in texts:
            low = t.lower()
            vec = [float(low.count(w)) for w in _VOCAB] + [0.01]
            rows.append(vec)
        return np.array(rows)


@pytest.fixture
def scf_sample():
    import copy

    return copy.deepcopy(SCF_SAMPLE)


@pytest.fixture
def fake_embeddings(monkeypatch, tmp_path):
    """Patch the embedding model and point the embedding cache at tmp_path."""
    import src.mapper as mapper

    model = FakeEmbeddingModel()
    monkeypatch.setattr(mapper, "_get_embedding_model", lambda: model)
    monkeypatch.setattr(
        mapper, "EMBEDDINGS_CACHE_FILE", str(tmp_path / "scf_embeddings.npz")
    )
    return model
