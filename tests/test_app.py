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
    mapper.load_scf_database.clear()
    yield db
    mapper.load_scf_database.clear()


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
