from unittest.mock import patch
import pytest
import requests
from pydantic import ValidationError

from src.fetch_scf import SCFControl, setup_directories


# --- SCFControl Pydantic schema tests ---


def test_scf_control_valid():
    control = SCFControl(
        control_id="CRY-01",
        domain="Cryptography",
        description="Encrypt all data at rest.",
        weight=5,
    )
    assert control.control_id == "CRY-01"
    assert control.weight == 5


def test_scf_control_sub_control():
    """Control IDs with a decimal sub-number should be accepted."""
    control = SCFControl(control_id="CRY-01.1", description="Sub-control.")
    assert control.control_id == "CRY-01.1"


def test_scf_control_defaults():
    control = SCFControl(control_id="GOV-01", description="Test")
    assert control.domain == ""
    assert control.erl == ""
    assert control.question == ""
    assert control.regulations == {}


def test_scf_control_invalid_id_format():
    with pytest.raises(ValidationError):
        SCFControl(control_id="BADFORMAT", description="Test")


def test_scf_control_weight_too_high():
    with pytest.raises(ValidationError):
        SCFControl(control_id="GOV-01", description="Test", weight=11)


def test_scf_control_weight_too_low():
    with pytest.raises(ValidationError):
        SCFControl(control_id="GOV-01", description="Test", weight=0)


# --- setup_directories ---


def test_setup_directories_creates_dir(tmp_path, monkeypatch):
    target = tmp_path / "data"
    import src.fetch_scf as fetch_scf_module

    monkeypatch.setattr(fetch_scf_module, "DATA_DIR", str(target))
    setup_directories()
    assert target.exists()


def test_setup_directories_existing_dir(tmp_path, monkeypatch):
    """Should not raise if the directory already exists."""
    import src.fetch_scf as fetch_scf_module

    monkeypatch.setattr(fetch_scf_module, "DATA_DIR", str(tmp_path))
    setup_directories()  # tmp_path already exists
    assert tmp_path.exists()


# --- download_scf ---


def test_download_scf_skips_when_file_exists(tmp_path, monkeypatch):
    """Returns True immediately if the raw file is already on disk."""
    import src.fetch_scf as fetch_scf_module

    existing = tmp_path / "scf_raw.xlsx"
    existing.write_bytes(b"fake")
    monkeypatch.setattr(fetch_scf_module, "RAW_SCF_FILE", str(existing))

    with patch("src.fetch_scf.requests.get") as mock_get:
        result = fetch_scf_module.download_scf()

    assert result is True
    mock_get.assert_not_called()


@patch("src.fetch_scf.requests.get")
def test_download_scf_http_error(mock_get, tmp_path, monkeypatch):
    """Returns False and logs on HTTP errors."""
    import src.fetch_scf as fetch_scf_module

    monkeypatch.setattr(
        fetch_scf_module, "RAW_SCF_FILE", str(tmp_path / "missing.xlsx")
    )
    mock_get.side_effect = requests.exceptions.HTTPError("404")
    result = fetch_scf_module.download_scf()
    assert result is False


@patch("src.fetch_scf.requests.get")
def test_download_scf_no_xlsx_asset(mock_get, tmp_path, monkeypatch):
    """Returns False when the GitHub release has no .xlsx asset."""
    import src.fetch_scf as fetch_scf_module

    monkeypatch.setattr(
        fetch_scf_module, "RAW_SCF_FILE", str(tmp_path / "missing.xlsx")
    )
    mock_response = mock_get.return_value.__enter__.return_value = mock_get.return_value
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {
        "assets": [{"name": "readme.txt", "browser_download_url": "http://x"}]
    }
    result = fetch_scf_module.download_scf()
    assert result is False


# --- download_scf: success, force and partial downloads ---


def _release_response(mock_get, body_chunks, fail_midway=False):
    """Configure requests.get: first call returns release JSON, second the file."""
    from unittest.mock import MagicMock

    api = MagicMock()
    api.raise_for_status.return_value = None
    api.json.return_value = {
        "assets": [
            {"name": "notes.txt", "browser_download_url": "http://x/notes"},
            {"name": "scf.xlsx", "browser_download_url": "http://x/scf.xlsx"},
        ]
    }

    def chunks(chunk_size):
        for i, c in enumerate(body_chunks):
            if fail_midway and i == 1:
                raise requests.exceptions.ConnectionError("dropped")
            yield c

    download = MagicMock()
    download.raise_for_status.return_value = None
    download.iter_content.side_effect = chunks
    mock_get.side_effect = [api, download]


@patch("src.fetch_scf.requests.get")
def test_download_scf_writes_file(mock_get, tmp_path, monkeypatch):
    import src.fetch_scf as fetch_scf_module

    target = tmp_path / "scf_raw.xlsx"
    monkeypatch.setattr(fetch_scf_module, "RAW_SCF_FILE", str(target))
    _release_response(mock_get, [b"abc", b"def"])

    assert fetch_scf_module.download_scf() is True
    assert target.read_bytes() == b"abcdef"
    assert mock_get.call_args_list[1].args[0] == "http://x/scf.xlsx"
    assert not (tmp_path / "scf_raw.xlsx.part").exists()


@patch("src.fetch_scf.requests.get")
def test_download_scf_force_replaces_existing(mock_get, tmp_path, monkeypatch):
    import src.fetch_scf as fetch_scf_module

    target = tmp_path / "scf_raw.xlsx"
    target.write_bytes(b"old")
    monkeypatch.setattr(fetch_scf_module, "RAW_SCF_FILE", str(target))
    _release_response(mock_get, [b"new"])

    assert fetch_scf_module.download_scf(force=True) is True
    assert target.read_bytes() == b"new"


@patch("src.fetch_scf.requests.get")
def test_download_scf_interrupted_keeps_previous_file(mock_get, tmp_path, monkeypatch):
    """A dropped connection must not leave a truncated workbook behind."""
    import src.fetch_scf as fetch_scf_module

    target = tmp_path / "scf_raw.xlsx"
    target.write_bytes(b"old")
    monkeypatch.setattr(fetch_scf_module, "RAW_SCF_FILE", str(target))
    _release_response(mock_get, [b"ne", b"w"], fail_midway=True)

    assert fetch_scf_module.download_scf(force=True) is False
    assert target.read_bytes() == b"old"
    assert not (tmp_path / "scf_raw.xlsx.part").exists()


# --- parse_scf on a small synthetic workbook ---


def _write_workbook(path, rows, columns, sheets=("SCF 2025.4",)):
    import pandas as pd

    with pd.ExcelWriter(path) as writer:
        pd.DataFrame({"x": [1]}).to_excel(
            writer, sheet_name="SCF Domains & Principles", index=False
        )
        for sheet in sheets:
            pd.DataFrame(rows, columns=columns).to_excel(
                writer, sheet_name=sheet, index=False
            )


COLUMNS = [
    "SCF Domain",
    "SCF #",
    "Secure Controls Framework (SCF)\nControl Description",
    "Relative Control Weighting",
    "Evidence Request List (ERL) #",
    "SCF Control Question",
    "AICPA\nSOC 2 (2017)",
    "EMEA\nEU\nGDPR",
    "Unrelated Column",
]


def _parse(tmp_path, monkeypatch, rows, columns=COLUMNS):
    import json

    import src.fetch_scf as fetch_scf_module

    raw = tmp_path / "scf_raw.xlsx"
    parsed = tmp_path / "scf_parsed.json"
    _write_workbook(raw, rows, columns)
    monkeypatch.setattr(fetch_scf_module, "RAW_SCF_FILE", str(raw))
    monkeypatch.setattr(fetch_scf_module, "PARSED_JSON_FILE", str(parsed))
    ok = fetch_scf_module.parse_scf()
    records = json.loads(parsed.read_text()) if parsed.exists() else None
    return ok, records


def test_parse_scf_extracts_records(tmp_path, monkeypatch):
    rows = [
        [
            "Cryptographic Protections",
            " CRY-01 ",
            "Use encryption.",
            10,
            "E-1",
            "Q?",
            "CC6.1",
            "Art 32",
            "zzz",
        ],
        ["Governance", "GOV-01", "Run a program.", None, None, None, None, None, None],
        ["Governance", "BAD ID", "Invalid id.", 5, None, None, None, None, None],
        ["Governance", None, "No id.", 5, None, None, None, None, None],
    ]
    ok, records = _parse(tmp_path, monkeypatch, rows)
    assert ok is True
    assert [r["control_id"] for r in records] == ["CRY-01", "GOV-01"]
    cry = records[0]
    assert cry["domain"] == "Cryptographic Protections"
    assert cry["weight"] == 10
    assert cry["erl"] == "E-1"
    assert cry["regulations"] == {
        "AICPA SOC 2 (2017)": "CC6.1",
        "EMEA EU GDPR": "Art 32",
    }
    gov = records[1]
    assert gov["weight"] == 1
    assert gov["regulations"] == {}


def test_parse_scf_without_domain_column(tmp_path, monkeypatch):
    columns = [c for c in COLUMNS if c != "SCF Domain"]
    rows = [["CRY-01", "Use encryption.", 3, None, None, None, None, None]]
    ok, records = _parse(tmp_path, monkeypatch, rows, columns)
    assert ok is True
    assert records[0]["domain"] == ""


def test_parse_scf_refuses_to_write_empty_database(tmp_path, monkeypatch):
    rows = [["Governance", "not-an-id", "x", 1, None, None, None, None, None]]
    ok, records = _parse(tmp_path, monkeypatch, rows)
    assert ok is False
    assert records is None


def test_parse_scf_missing_required_columns(tmp_path, monkeypatch):
    ok, records = _parse(tmp_path, monkeypatch, [["a", "b"]], ["Foo", "Bar"])
    assert ok is False
    assert records is None
