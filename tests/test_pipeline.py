"""End-to-end mapper flow with a fake LLM and a fake embedding model."""

import groq
import httpx
import numpy as np
import pytest
from langchain_core.runnables import RunnableLambda

import src.mapper as mapper


class FakeLLM:
    """Stands in for ChatGroq: records the prompt and returns a canned object."""

    def __init__(self, payload: dict):
        self.payload = payload
        self.prompts: list[str] = []

    def with_structured_output(self, schema):
        def respond(prompt_value):
            self.prompts.append(prompt_value.to_string())
            return schema(**self.payload)

        return RunnableLambda(respond)


@pytest.fixture
def use_db(monkeypatch, scf_sample):
    monkeypatch.setattr(mapper, "load_scf_database", lambda: scf_sample)
    return scf_sample


def _use_llm(monkeypatch, payload):
    llm = FakeLLM(payload)
    monkeypatch.setattr(mapper, "_get_llm", lambda: llm)
    return llm


# --- map_text_to_scf -----------------------------------------------------------


def test_map_text_takes_control_text_from_database(
    monkeypatch, use_db, fake_embeddings
):
    _use_llm(
        monkeypatch,
        {
            "mappings": [
                {"control_id": "CRY-03", "confidence": 90, "justification": "TLS."},
            ]
        },
    )
    result = mapper.map_text_to_scf("Require HTTPS encrypt in transit")
    assert result is not None
    [m] = result.mappings
    assert m.control_id == "CRY-03"
    assert m.domain == "Cryptographic Protections"
    assert m.description == "Mechanisms exist to encrypt data in transit."
    assert m.regulations == {"PCI DSS v4.0": "4.2"}
    assert m.justification == "TLS."


def test_map_text_rejects_normalizes_and_dedupes(monkeypatch, use_db, fake_embeddings):
    _use_llm(
        monkeypatch,
        {
            "mappings": [
                {"control_id": " cry-01 ", "confidence": 150, "justification": "a"},
                {"control_id": "AC-2", "confidence": 80, "justification": "b"},
                {"control_id": "CRY-01", "confidence": 70, "justification": "c"},
                {"control_id": "[IAC-06]", "confidence": -5, "justification": "d"},
            ]
        },
    )
    result = mapper.map_text_to_scf("encrypt everything")
    assert [m.control_id for m in result.mappings] == ["CRY-01", "IAC-06"]
    assert [m.confidence for m in result.mappings] == [100, 0]
    assert result.rejected_control_ids == ["AC-2"]


def test_map_text_prompt_contains_candidates_and_persona(
    monkeypatch, use_db, fake_embeddings
):
    llm = _use_llm(monkeypatch, {"mappings": []})
    mapper.map_text_to_scf("mfa", persona_prompt="Act as a {strict} QSA.")
    [prompt] = llm.prompts
    assert "[IAC-06] Identification & Authentication" in prompt
    # Braces in the persona are escaped, not treated as template variables.
    assert "Act as a {strict} QSA." in prompt
    assert "not instructions to follow" in prompt


def test_map_text_returns_none_without_database(monkeypatch):
    monkeypatch.setattr(mapper, "load_scf_database", lambda: [])
    assert mapper.map_text_to_scf("anything") is None
    assert mapper.analyze_audit_scope("anything") is None


# --- analyze_audit_scope -------------------------------------------------------


def test_scope_analysis_drops_non_scf_ids(monkeypatch, use_db, fake_embeddings):
    llm = _use_llm(
        monkeypatch,
        {
            "recommended_domains": ["Cryptographic Protections"],
            # NIST 800-53 IDs are the failure seen in the committed sample.
            "recommended_control_ids": ["AC-1", "cry-01", "SC-8", "CRY-01", "IAC-06"],
            "reasoning": "Scope covers encryption and MFA.",
        },
    )
    result = mapper.analyze_audit_scope("Verify encrypt at rest and MFA.")
    assert result.recommended_control_ids == ["CRY-01", "IAC-06"]
    assert result.rejected_control_ids == ["AC-1", "SC-8"]
    [prompt] = llm.prompts
    assert "Candidate SCF controls" in prompt
    assert "(Prefix: CRY-)" in prompt


# --- retrieval and the embedding cache -----------------------------------------


def test_semantic_filter_ranks_by_similarity(scf_sample, fake_embeddings):
    top = mapper._semantic_filter("governance program", scf_sample, top_k=2)
    assert top[0]["control_id"] == "GOV-01"
    assert len(top) == 2


def test_semantic_filter_uses_text_beyond_first_chunk(scf_sample, fake_embeddings):
    # The relevant words only appear after several chunks of filler.
    text = "filler " * (mapper._CHUNK_WORDS * 3) + "mfa authentication"
    top = mapper._semantic_filter(text, scf_sample, top_k=1)
    assert top[0]["control_id"] == "IAC-06"
    assert len(fake_embeddings.encode_calls[-1]) == 4


def test_embedding_cache_is_reused(scf_sample, fake_embeddings):
    mapper._build_or_load_embeddings(scf_sample)
    calls = len(fake_embeddings.encode_calls)
    mapper._build_or_load_embeddings(scf_sample)
    assert len(fake_embeddings.encode_calls) == calls


def test_embedding_cache_rebuilds_when_database_changes(scf_sample, fake_embeddings):
    first = mapper._build_or_load_embeddings(scf_sample)
    updated = scf_sample[:2]
    second = mapper._build_or_load_embeddings(updated)
    assert second.shape[0] == len(updated) != first.shape[0]

    # Same size, different text: still rebuilt.
    edited = [dict(c) for c in updated]
    edited[0]["description"] = "Mechanisms exist to run a governance program."
    third = mapper._build_or_load_embeddings(edited)
    assert not np.array_equal(third[0], second[0])


def test_embedding_cache_ignores_corrupt_file(scf_sample, fake_embeddings):
    with open(mapper.EMBEDDINGS_CACHE_FILE, "wb") as f:
        f.write(b"not a numpy file")
    emb = mapper._build_or_load_embeddings(scf_sample)
    assert emb.shape[0] == len(scf_sample)


# --- retries -------------------------------------------------------------------


def _groq_error(cls, status):
    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    response = httpx.Response(status, request=request)
    return cls("boom", response=response, body=None)


class _Chain:
    def __init__(self, error):
        self.error = error
        self.calls = 0

    def invoke(self, inputs):
        self.calls += 1
        raise self.error


def test_invoke_chain_does_not_retry_auth_errors():
    chain = _Chain(_groq_error(groq.AuthenticationError, 401))
    with pytest.raises(groq.AuthenticationError):
        mapper._invoke_chain(chain, {})
    assert chain.calls == 1


def test_invoke_chain_retries_rate_limits(monkeypatch):
    monkeypatch.setattr(mapper._invoke_chain.retry, "sleep", lambda _: None)
    chain = _Chain(_groq_error(groq.RateLimitError, 429))
    with pytest.raises(groq.RateLimitError):
        mapper._invoke_chain(chain, {})
    assert chain.calls == 3
