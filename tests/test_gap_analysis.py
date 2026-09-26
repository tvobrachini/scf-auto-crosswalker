import pandas as pd

from src.gap_analysis import (
    STATUS_COVERED,
    STATUS_GAP,
    analyze_gaps,
    detect_id_column,
    framework_columns,
)


def test_framework_columns_ignore_case_and_spaces(scf_sample):
    assert framework_columns(scf_sample, "SOC 2") == ["AICPA SOC 2 (2017)"]
    assert framework_columns(scf_sample, "iso27001") == [
        "ISO 27001 v2013",
        "ISO 27001 v2022",
    ]
    assert framework_columns(scf_sample, "HIPAA") == []


def test_detect_id_column():
    df = pd.DataFrame({"Name": ["x"], "Control ID": ["CRY-01"]})
    assert detect_id_column(df) == "Control ID"
    assert detect_id_column(pd.DataFrame({"Ref": ["CRY-01"]})) == "Ref"


def test_analyze_gaps_marks_listed_and_missing(scf_sample):
    existing = pd.DataFrame(
        {"Control ID": [" cry-01", "SEC-01", None], "Control Name": ["a", "b", "c"]}
    )
    report = analyze_gaps(scf_sample, ["AICPA SOC 2 (2017)"], existing)

    status = {r["SCF Control ID"]: r["Status"] for r in report.rows}
    assert status == {"CRY-01": STATUS_COVERED, "IAC-06": STATUS_GAP}
    assert (report.covered, report.gaps) == (1, 1)
    # Non-SCF IDs are reported instead of silently never matching.
    assert report.unknown_ids == ["SEC-01"]
    assert report.rows[0]["Framework References"] == "AICPA SOC 2 (2017): CC6.1"


def test_analyze_gaps_one_edition_only(scf_sample):
    existing = pd.DataFrame({"Control ID": ["GOV-01"]})
    report = analyze_gaps(scf_sample, ["ISO 27001 v2013"], existing)
    assert [r["SCF Control ID"] for r in report.rows] == ["GOV-01"]
    assert report.gaps == 0


def test_analyze_gaps_explicit_id_column(scf_sample):
    existing = pd.DataFrame({"Mapped SCF": ["IAC-06"], "Other ID": ["CRY-01"]})
    report = analyze_gaps(scf_sample, ["AICPA SOC 2 (2017)"], existing, "Mapped SCF")
    status = {r["SCF Control ID"]: r["Status"] for r in report.rows}
    assert status["IAC-06"] == STATUS_COVERED
    assert status["CRY-01"] == STATUS_GAP
