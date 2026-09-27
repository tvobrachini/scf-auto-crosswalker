import pandas as pd

from gap_analysis import (
    REQ_ADDRESSED,
    REQ_OPEN,
    STATUS_COVERED,
    STATUS_GAP,
    analyze_gaps,
    detect_id_column,
    framework_columns,
    requirement_coverage,
    requirement_key,
    split_refs,
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


def test_detect_id_column_uses_whole_words():
    df = pd.DataFrame(
        {
            "Control Provider": ["x"],
            "Control Validation": ["y"],
            "Control ID": ["CRY-01"],
        }
    )
    assert detect_id_column(df) == "Control ID"
    df = pd.DataFrame({"Name": ["x"], "SCF ID": ["CRY-01"]})
    assert detect_id_column(df) == "SCF ID"
    df = pd.DataFrame({"control_provider": ["x"], "ref": ["CRY-01"]})
    assert detect_id_column(df) == "control_provider"


def test_status_filter_excludes_controls_not_in_place(scf_sample):
    from gap_analysis import default_in_place_statuses, detect_status_column

    existing = pd.DataFrame(
        {
            "Control ID": ["CRY-01", "IAC-06"],
            "Status": ["Implemented", "Not Implemented"],
        }
    )
    assert detect_status_column(existing) == "Status"
    statuses = [
        "Implemented",
        "Not Implemented",
        "Partially implemented",
        "Planned",
        "In Place",
    ]
    assert default_in_place_statuses(statuses) == ["Implemented", "In Place"]

    report = analyze_gaps(
        scf_sample,
        ["AICPA SOC 2 (2017)"],
        existing,
        "Control ID",
        status_column="Status",
        in_place_statuses=["Implemented"],
    )
    status = {r["SCF Control ID"]: r["Status"] for r in report.rows}
    assert status == {"CRY-01": STATUS_COVERED, "IAC-06": STATUS_GAP}
    assert report.excluded_by_status == ["IAC-06"]


def test_split_refs_and_requirement_key():
    assert split_refs("CC1.1\nCC1.1-POF1; CC1.2, ") == ["CC1.1", "CC1.1-POF1", "CC1.2"]
    soc = "AICPA TSC 2017:2022 (used for SOC 2)"
    assert requirement_key(soc, "CC1.1-POF12") == "CC1.1"
    assert requirement_key("ISO 27001 2022", "6.1.1(e)(1)") == "6.1.1"
    assert requirement_key("ISO 27001 2022", "5.1(a)") == "5.1"
    # Other frameworks keep SCF's reference as written.
    assert requirement_key("HIPAA", "164.308(a)(5)") == "164.308(a)(5)"
    assert requirement_key("PCI DSS 4.0.1", "12.1.1") == "12.1.1"
    assert requirement_key("HIPAA", "164.312(a)(2)(iv)") == "164.312(a)(2)(iv)"
    assert requirement_key("ISO 27001 2022", "3.0") == "3.0"
    # TSC category headings are not criteria.
    assert requirement_key(soc, "P1.0") is None
    assert requirement_key(soc, "CC1.1") == "CC1.1"
    assert split_refs("GOV-01 | CRY-03") == ["GOV-01", "CRY-03"]


def test_requirement_coverage_rolls_up_and_counts_listed():
    col = "AICPA SOC 2 (2017)"
    scf = [
        {"control_id": "CRY-01", "regulations": {col: "CC6.1\nCC6.1-POF3"}},
        {"control_id": "CRY-02", "regulations": {col: "CC6.1\nCC6.7"}},
        {"control_id": "GOV-01", "regulations": {col: "CC10.1\nP1.0"}},
        {"control_id": "HRS-01", "regulations": {"HIPAA": "164.308"}},
    ]
    rows = requirement_coverage(scf, [col], {"CRY-02"})
    # Natural order: CC6.x before CC10.1; POF3 rolled into CC6.1, no duplicate ID.
    assert [r["Requirement"] for r in rows] == ["CC6.1", "CC6.7", "CC10.1"]
    assert rows[0] == {
        "Status": REQ_ADDRESSED,
        "Requirement": "CC6.1",
        "SCF controls mapped": 2,
        "Listed SCF controls": "CRY-02",
        "Not listed SCF controls": "CRY-01",
    }
    assert rows[2]["Status"] == REQ_OPEN
    # With several columns, the column prefixes the requirement.
    both = requirement_coverage(scf, [col, "HIPAA"], set())
    assert "HIPAA: 164.308" in [r["Requirement"] for r in both]


def test_report_counts_requirements(scf_sample):
    df = pd.DataFrame({"Control ID": ["CRY-01"]})
    report = analyze_gaps(scf_sample, ["AICPA SOC 2 (2017)"], df)
    assert report.requirements
    assert report.requirements_addressed == sum(
        1 for r in report.requirements if r["Listed SCF controls"]
    )
    assert report.requirements_addressed >= 1


def test_own_numbering_with_a_mapping_column(scf_sample):
    """A list with its own IDs and an SCF mapping column (several IDs per cell)."""
    df = pd.DataFrame(
        {
            "Control ID": ["SEC-01", "SEC-02"],
            "SCF Mapping": ["CRY-01; IAC-06", "NOT-AN-ID"],
        }
    )
    known = {c["control_id"] for c in scf_sample}
    assert detect_id_column(df, known) == "SCF Mapping"
    # Own numbering that collides with one known ID loses to the mapping column.
    collide = pd.DataFrame(
        {
            "Control ID": ["CRY-01", "ACME-2", "ACME-3"],
            "Mapping": ["IAC-06", "", "GOV-01"],
        }
    )
    assert detect_id_column(collide, known) == "Mapping"
    # No column names a known ID: fall back to the header rules.
    assert detect_id_column(df, {"ZZZ-99"}) == "Control ID"
    report = analyze_gaps(scf_sample, ["AICPA SOC 2 (2017)"], df, "SCF Mapping")
    listed = {r["SCF Control ID"] for r in report.rows if r["Status"] == STATUS_COVERED}
    assert "CRY-01" in listed
    assert report.unknown_ids == ["NOT-AN-ID"]
