"""Headless UI tests with Streamlit's AppTest. No LLM, network or real SCF data."""

import json
import os
import sys

import pytest
from streamlit.testing.v1 import AppTest

from tests.conftest import SCF_SAMPLE

ROOT = os.path.dirname(os.path.dirname(__file__))
APP = os.path.join(ROOT, "app.py")
SRC = os.path.join(ROOT, "src")

TOOLS = [
    "🔍 SCF Auto-Crosswalker",
    "📉 Compliance Gap Analyzer",
    "🎯 Audit Scope Analyzer",
]


@pytest.fixture
def scf_db(tmp_path, monkeypatch):
    """Point the app's `mapper` module (imported via src/ on sys.path) at a fixture DB."""
    if SRC not in sys.path:
        sys.path.append(SRC)
    import mapper

    db = tmp_path / "scf_parsed.json"
    db.write_text(json.dumps(SCF_SAMPLE), encoding="utf-8")
    monkeypatch.setattr(mapper, "PARSED_JSON_FILE", str(db))
    mapper.clear_scf_cache()
    yield db
    mapper.clear_scf_cache()


def _app(tool: str) -> AppTest:
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    at.sidebar.radio[0].set_value(tool).run()
    return at


@pytest.mark.parametrize("tool", TOOLS)
def test_each_tool_renders(scf_db, tool):
    at = _app(tool)
    assert not at.exception
    assert at.title[0].value == tool


def test_gap_analyzer_with_lab_csv(scf_db):
    at = _app("📉 Compliance Gap Analyzer")
    at.selectbox(key="gap_lab").set_value("sample_existing_controls.csv").run()
    at.button(key="gap_btn").click().run()
    assert not at.exception

    metrics = {m.label: m.value for m in at.metric}
    assert metrics["SCF controls mapped"] == "2"
    # The lab list uses its own IDs (SEC-01, ...), which is flagged.
    assert any("not SCF control IDs" in w.value for w in at.warning)


def test_crosswalker_requires_input(scf_db):
    at = _app("🔍 SCF Auto-Crosswalker")
    at.button(key="cw_btn").click().run()
    assert not at.exception
    assert any("Please provide some text" in w.value for w in at.warning)


def test_crosswalker_lab_picker_lists_inputs_only(scf_db):
    at = _app("🔍 SCF Auto-Crosswalker")
    options = at.selectbox(key="cw_lab").options
    assert "README.md" not in options
    assert "sample_endpoint_policy.txt" in options
    assert "aws_securityhub_finding.json" in options


# --- Success paths with a fake model ---------------------------------------------

EVIL = "![x](https://evil.example/leak.png) [click](https://evil.example)"


@pytest.fixture
def fake_model(scf_db, monkeypatch, tmp_path):
    """Fake Groq and embeddings inside the `mapper` module the app imports."""
    import mapper

    from tests.conftest import FakeEmbeddingModel
    from tests.test_pipeline import FakeLLM

    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setattr(mapper, "_get_embedding_model", lambda: FakeEmbeddingModel())
    monkeypatch.setattr(
        mapper, "EMBEDDINGS_CACHE_FILE", str(tmp_path / "emb" / "scf_embeddings.npz")
    )
    monkeypatch.setattr(mapper, "_embeddings_memo", {})
    llm = FakeLLM(
        {
            "mappings": [
                {"control_id": "CRY-03", "confidence": 0.9, "justification": EVIL},
                {"control_id": "AC-2", "confidence": 80, "justification": "nist id"},
            ],
            "recommended_domains": ["Cryptographic Protections", "Access Control"],
            "recommended_control_ids": ["CRY-01", "SC-8"],
            "reasoning": EVIL,
        }
    )
    monkeypatch.setattr(mapper, "_get_llm", lambda: llm)
    return llm


def _download_labels(at):
    return [e.proto.label for e in at.get("download_button")]


def _markdown(at):
    return [m.value for m in at.markdown]


def test_crosswalker_single_input_success(fake_model):
    at = _app("🔍 SCF Auto-Crosswalker")
    at.text_area[0].set_value("Require HTTPS encrypt in transit").run()
    at.button(key="cw_btn").click().run()
    assert not at.exception

    assert any("Suggestions ready" in s.value for s in at.success)
    assert any("CRY-03" in e.label for e in at.expander)
    # The non-candidate ID is reported, not shown as a suggestion.
    assert any("AC\\-2" in w.value for w in at.warning)
    # Model text is escaped: no live image or link reaches the page.
    assert not any("![x](" in m or "](https://evil" in m for m in _markdown(at))
    assert any("\\!\\[x\\]" in m for m in _markdown(at))
    assert _download_labels(at) == [
        "📥 Download All Suggestions (CSV)",
        "📥 Download OSCAL Mapping (JSON)",
    ]

    # Results survive the rerun a download click triggers.
    at.run()
    assert any("CRY-03" in e.label for e in at.expander)


def test_crosswalker_batch_success(fake_model):
    at = _app("🔍 SCF Auto-Crosswalker")
    at.selectbox(key="cw_lab").set_value("aws_securityhub_finding.json").run()
    at.button(key="cw_btn").click().run()
    assert not at.exception
    assert any("Batch mapping complete" in s.value for s in at.success)
    assert any(e.label.startswith("#1 | CRY-03") for e in at.expander)
    assert any("CloudFront\\.3" in m for m in _markdown(at))
    assert "📥 Download Ranked Summary (CSV)" in _download_labels(at)


def test_scope_analyzer_success(fake_model):
    at = _app("🎯 Audit Scope Analyzer")
    at.text_area[0].set_value("Verify encryption at rest and MFA.").run()
    at.button(key="scope_btn").click().run()
    assert not at.exception
    assert any("CRY-01" in m for m in _markdown(at))
    warnings = " ".join(w.value for w in at.warning)
    assert "SC\\-8" in warnings  # NIST ID rejected
    assert "Access Control" in warnings  # not an SCF domain
    assert not any("](https://evil" in i.value for i in at.info)
    assert _download_labels(at) == ["📥 Download Test Plan as CSV"]
