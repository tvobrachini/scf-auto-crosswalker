"""DEMO_MODE: activation, the synthetic catalog, the canned model and the UI. Offline."""

import csv
import io
import json
import os
import re
import sys

import numpy as np
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

import demo
import mapper
from crosswalk import CrosswalkInput, run_crosswalk
from demo import (
    DEMO_BADGE,
    DEMO_CATALOG,
    DEMO_NOTICE,
    DEMO_REJECTED_ID,
    CannedChatModel,
    DemoEmbeddingModel,
    DemoModeNotAllowedError,
    demo_mode_enabled,
)
from exports import DEMO_COLUMN, oscal_mapping_collection, to_safe_csv
from fetch_scf import SCFControl
from gap_analysis import analyze_gaps, framework_columns

ROOT = os.path.dirname(os.path.dirname(__file__))
APP = os.path.join(ROOT, "app.py")
SRC = os.path.join(ROOT, "src")
LAB = os.path.join(ROOT, "lab_data")


@pytest.fixture
def demo_on(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)


@pytest.fixture
def demo_off(monkeypatch):
    monkeypatch.delenv("DEMO_MODE", raising=False)


# --- Activation ---------------------------------------------------------------------


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on", " On "])
def test_demo_mode_truthy_values(monkeypatch, value):
    monkeypatch.setenv("DEMO_MODE", value)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    assert demo_mode_enabled()


@pytest.mark.parametrize("value", ["", "0", "false", "no", "off", "demo", "2"])
def test_demo_mode_falsy_values(monkeypatch, value):
    monkeypatch.setenv("DEMO_MODE", value)
    assert not demo_mode_enabled()


def test_demo_mode_is_off_by_default(demo_off, monkeypatch, tmp_path):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setattr(mapper, "PARSED_JSON_FILE", str(tmp_path / "missing.json"))
    assert not demo_mode_enabled()
    # The real implementations are used.
    assert not isinstance(mapper._get_llm(), CannedChatModel)
    assert mapper.load_scf_database() == []


@pytest.mark.parametrize("env", ["production", "PROD", "staging"])
def test_demo_mode_refused_in_production(monkeypatch, env):
    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.setenv("ENVIRONMENT", env)
    with pytest.raises(DemoModeNotAllowedError):
        demo_mode_enabled()


def test_demo_mode_allowed_in_local_environment(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.setenv("ENVIRONMENT", "development")
    assert demo_mode_enabled()


# --- Synthetic catalog ------------------------------------------------------------


def test_catalog_records_pass_the_scf_schema():
    assert 12 <= len(DEMO_CATALOG) <= 20
    for record in DEMO_CATALOG:
        SCFControl(**record)


def test_catalog_is_visibly_synthetic():
    ids = [c["control_id"] for c in DEMO_CATALOG]
    assert len(ids) == len(set(ids))
    # Made-up domain prefixes starting with D; no SCF domain prefixes.
    assert all(re.match(r"^D[A-Z]{3}-\d{2}$", cid) for cid in ids)
    assert all(c["domain"].startswith("Demo ") for c in DEMO_CATALOG)


def test_catalog_crosswalk_columns_work_with_gap_analysis():
    for framework in ["SOC 2", "ISO 27001", "NIST CSF", "NIST 800-53", "GDPR"]:
        assert framework_columns(DEMO_CATALOG, framework), framework


def test_load_scf_database_returns_catalog_in_demo(demo_on, monkeypatch, tmp_path):
    monkeypatch.setattr(mapper, "PARSED_JSON_FILE", str(tmp_path / "missing.json"))
    assert mapper.load_scf_database() is DEMO_CATALOG


# --- Embedder and canned model ------------------------------------------------------


def test_embedder_is_deterministic_and_normalized():
    texts = ["Encrypt data in transit with TLS", "", "MFA for admins"]
    a = DemoEmbeddingModel().encode(texts)
    b = DemoEmbeddingModel().encode(texts, convert_to_numpy=True)
    assert np.array_equal(a, b)
    assert np.allclose(np.linalg.norm(a[[0, 2]], axis=1), 1.0)
    assert not a[1].any()


def test_demo_pipeline_is_deterministic_and_offline(demo_on, monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("demo mode must not load real models")

    monkeypatch.setattr(mapper, "SentenceTransformer", no_network)
    monkeypatch.setattr(mapper, "ChatGroq", no_network)

    text = "CloudFront distributions should require encryption in transit (HTTPS)."
    first = mapper.map_text_to_scf(text)
    second = mapper.map_text_to_scf(text)
    assert first is not None and second is not None
    assert first.model_dump() == second.model_dump()

    ids = [m.control_id for m in first.mappings]
    assert ids[0] == "DCRY-02"
    assert len(ids) == 3
    assert [m.confidence for m in first.mappings] == [82, 64, 47]
    assert all(m.justification.startswith("DEMO OUTPUT") for m in first.mappings)
    # Enrichment comes from the catalog, and the planted ID is rejected.
    by_id = {c["control_id"]: c for c in DEMO_CATALOG}
    assert first.mappings[0].description == by_id["DCRY-02"]["description"]
    assert first.mappings[0].regulations == by_id["DCRY-02"]["regulations"]
    assert first.rejected_control_ids == [DEMO_REJECTED_ID]


def test_demo_scope_analysis(demo_on):
    with open(os.path.join(LAB, "sample_audit_scope.txt"), encoding="utf-8") as f:
        scope = f.read()
    result = mapper.analyze_audit_scope(scope)
    assert result is not None
    assert len(result.recommended_control_ids) == 6
    assert result.rejected_control_ids == [DEMO_REJECTED_ID]
    assert result.rejected_domains == []
    assert result.recommended_domains
    assert result.reasoning.startswith("DEMO OUTPUT")
    assert result == mapper.analyze_audit_scope(scope)


def test_canned_model_rejects_unknown_schema():
    from langchain_core.prompts import ChatPromptTemplate
    from pydantic import BaseModel

    class Other(BaseModel):
        x: int

    chain = ChatPromptTemplate.from_messages([("user", "hi")])
    runnable = chain | CannedChatModel().with_structured_output(Other)
    with pytest.raises(TypeError):
        runnable.invoke({})


def test_demo_batch_runs_through_real_crosswalk(demo_on):
    inputs = [
        CrosswalkInput("a", "Require MFA for developers", "IAM.6"),
        CrosswalkInput("b", "Require MFA for developers", "IAM.6"),
        CrosswalkInput("c", "Back up the databases daily"),
    ]
    results = run_crosswalk(inputs, lambda t, k: mapper.map_text_to_scf(t, top_k=k))
    assert all(r.error is None for r in results)
    assert results[0].mappings[0].control_id == "DIAM-02"
    assert results[2].mappings[0].control_id == "DBCR-01"


# --- Stamped exports ----------------------------------------------------------------


def test_csv_export_is_stamped_in_demo(demo_on):
    rows = list(
        csv.reader(io.StringIO(to_safe_csv(pd.DataFrame({"a": [1, 2]})).decode()))
    )
    assert rows[0] == [DEMO_COLUMN, "a"]
    assert all(r[0] == DEMO_NOTICE for r in rows[1:])


def test_csv_export_not_stamped_by_default(demo_off):
    rows = list(csv.reader(io.StringIO(to_safe_csv(pd.DataFrame({"a": [1]})).decode())))
    assert rows[0] == ["a"]


def test_oscal_export_is_stamped_in_demo(demo_on):
    result = mapper.map_text_to_scf("encryption in transit HTTPS")
    from crosswalk import CrosswalkResult

    doc = oscal_mapping_collection(
        [
            CrosswalkResult(
                input=CrosswalkInput("x", "x", "CloudFront.3"),
                mappings=result.mappings,
            )
        ],
        scf_version="SCF 2025.4",
    )["mapping-collection"]
    assert doc["metadata"]["title"].startswith("[DEMO DATA]")
    assert DEMO_NOTICE in doc["metadata"]["remarks"]
    assert "SCF 2025.4" not in json.dumps(doc)
    assert doc["provenance"]["mapping-description"].startswith(DEMO_NOTICE)
    titles = [r["title"] for r in doc["back-matter"]["resources"]]
    assert demo.DEMO_CATALOG_TITLE in titles

    mapping = pytest.importorskip("trestle.oscal.mapping")
    mapping.Model.model_validate_json(json.dumps({"mapping-collection": doc}))


def test_oscal_export_not_stamped_by_default(demo_off):
    doc = oscal_mapping_collection([])["mapping-collection"]
    assert "DEMO" not in doc["metadata"]["title"]
    assert "DEMO" not in doc["provenance"]["mapping-description"]


def test_demo_gap_analysis_on_demo_lab_csv():
    df = pd.read_csv(os.path.join(LAB, "demo_existing_controls.csv"))
    [column] = framework_columns(DEMO_CATALOG, "SOC 2")
    report = analyze_gaps(DEMO_CATALOG, [column], df)
    assert report.covered > 0 and report.gaps > 0
    assert report.unknown_ids == ["SEC-99"]


# --- The app in demo mode -------------------------------------------------------------


def _app(tool: str) -> AppTest:
    if SRC not in sys.path:
        sys.path.append(SRC)
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    at.sidebar.radio[0].set_value(tool).run()
    return at


def _badges(at) -> list[str]:
    return [m.value for m in at.markdown if DEMO_BADGE in m.value]


def _sidebar_badges(at) -> list[str]:
    return [m.value for m in at.sidebar.markdown if DEMO_BADGE in m.value]


def _download_labels(at):
    return [e.proto.label for e in at.get("download_button")]


def test_app_crosswalker_single_in_demo(demo_on):
    at = _app("🔍 SCF Auto-Crosswalker")
    assert _badges(at) and _sidebar_badges(at)
    # The SCF download button is not offered in demo mode.
    assert not [b for b in at.sidebar.button if "Download" in b.label]

    at.selectbox(key="cw_lab").set_value("sample_endpoint_policy.txt").run()
    at.button(key="cw_btn").click().run()
    assert not at.exception
    assert not at.error
    assert any("Suggestions ready" in s.value for s in at.success)
    assert any(e.label.startswith("Suggestion #1 | D") for e in at.expander)
    assert any("AC\\-2" in w.value for w in at.warning)
    assert _download_labels(at) == [
        "📥 Download All Suggestions (CSV)",
        "📥 Download OSCAL Mapping (JSON)",
    ]
    assert _badges(at)


def test_app_crosswalker_batch_in_demo(demo_on):
    at = _app("🔍 SCF Auto-Crosswalker")
    at.selectbox(key="cw_lab").set_value("aws_securityhub_finding.json").run()
    at.button(key="cw_btn").click().run()
    assert not at.exception
    assert any("Batch mapping complete" in s.value for s in at.success)
    assert any(e.label.startswith("#1 | DCRY-02") for e in at.expander)
    assert "📥 Download Ranked Summary (CSV)" in _download_labels(at)
    assert _badges(at)


def test_app_gap_analyzer_in_demo(demo_on):
    at = _app("📉 Compliance Gap Analyzer")
    assert _badges(at)
    at.selectbox(key="gap_lab").set_value("demo_existing_controls.csv").run()
    at.button(key="gap_btn").click().run()
    assert not at.exception
    metrics = {m.label: m.value for m in at.metric}
    assert int(metrics["SCF controls mapped"]) > 0
    assert any("SEC\\-99" in w.value for w in at.warning)


def test_app_scope_analyzer_in_demo(demo_on):
    at = _app("🎯 Audit Scope Analyzer")
    at.selectbox(key="scope_lab").set_value("sample_audit_scope.txt").run()
    at.button(key="scope_btn").click().run()
    assert not at.exception
    assert not at.error
    assert any("AC\\-2" in w.value for w in at.warning)
    assert any("DEMO OUTPUT" in i.value for i in at.info)
    assert _download_labels(at) == ["📥 Download Test Plan as CSV"]
    assert _badges(at)


def test_app_has_no_badge_by_default(demo_off, monkeypatch, tmp_path):
    monkeypatch.setattr(mapper, "PARSED_JSON_FILE", str(tmp_path / "missing.json"))
    at = _app("🔍 SCF Auto-Crosswalker")
    assert not at.exception
    assert not _badges(at) and not _sidebar_badges(at)
    assert [b for b in at.sidebar.button if "Download" in b.label]


def test_app_refuses_demo_in_production(demo_on, monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    assert not at.exception
    assert any("not allowed" in e.value for e in at.error)
    assert not at.sidebar.radio


def test_gap_lab_picker_lists_only_files_that_can_match(demo_on):
    """In demo mode only the demo control list is offered, and vice versa."""
    at = _app("📉 Compliance Gap Analyzer")
    options = at.selectbox(key="gap_lab").options
    assert "demo_existing_controls.csv" in options
    assert "sample_existing_controls.csv" not in options
