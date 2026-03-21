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
