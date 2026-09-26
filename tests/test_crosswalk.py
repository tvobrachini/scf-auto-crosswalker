from crosswalk import (
    CrosswalkInput,
    aggregate,
    all_rejected,
    detail_rows,
    run_crosswalk,
    unique_model_calls,
)
from mapper import MappedControl, MappingResult


def _mapped(cid, confidence, justification="j"):
    return MappedControl(
        control_id=cid,
        domain="D",
        description=f"{cid} text",
        confidence=confidence,
        justification=justification,
    )


class FakeMapper:
    def __init__(self, table, rejected=None, fail_on=None):
        self.table = table
        self.rejected = rejected or {}
        self.fail_on = fail_on
        self.calls: list[str] = []

    def __call__(self, text, top_k):
        self.calls.append(text)
        if text == self.fail_on:
            raise RuntimeError("boom")
        return MappingResult(
            mappings=self.table.get(text, []),
            rejected_control_ids=self.rejected.get(text, []),
        )


def test_identical_findings_cost_one_model_call():
    inputs = [
        CrosswalkInput("Finding 1", "same", "CloudFront.3"),
        CrosswalkInput("Finding 2", "same", "CloudFront.3"),
        CrosswalkInput("Finding 3", "other", "S3.1"),
    ]
    fake = FakeMapper(
        {"same": [_mapped("CRY-03", 90)], "other": [_mapped("CRY-01", 50)]}
    )
    results = run_crosswalk(inputs, fake)
    assert fake.calls == ["same", "other"]
    assert unique_model_calls(inputs) == 2
    assert [r.input.label for r in results] == ["Finding 1", "Finding 2", "Finding 3"]
    assert [m.control_id for m in results[1].mappings] == ["CRY-03"]


def test_error_on_one_input_does_not_stop_the_batch():
    inputs = [CrosswalkInput("A", "bad"), CrosswalkInput("B", "good")]
    fake = FakeMapper({"good": [_mapped("CRY-01", 70)]}, fail_on="bad")
    results = run_crosswalk(inputs, fake)
    assert results[0].error == "RuntimeError: boom"
    assert results[1].error is None
    assert results[1].mappings


def test_missing_database_is_reported():
    [r] = run_crosswalk([CrosswalkInput("A", "x")], lambda text, k: None)
    assert r.error == "The SCF database is not available."


def test_progress_is_reported():
    seen = []
    run_crosswalk(
        [CrosswalkInput("A", "a"), CrosswalkInput("B", "b")],
        FakeMapper({}),
        on_progress=lambda done, total: seen.append((done, total)),
    )
    assert seen == [(1, 2), (2, 2)]


def test_priority_score_is_confidence_weighted():
    inputs = [CrosswalkInput(f"F{i}", f"t{i}", f"X.{i}") for i in range(3)]
    fake = FakeMapper(
        {
            # Two weak hits on GOV-01 ...
            "t0": [_mapped("GOV-01", 10, "weak")],
            "t1": [_mapped("GOV-01", 10, "weak"), _mapped("CRY-01", 95, "strong")],
            # ... one strong hit on CRY-01 and one on GOV-01
            "t2": [_mapped("GOV-01", 60, "best")],
        }
    )
    scf = {"GOV-01": {"weight": 5}, "CRY-01": {"weight": 5}}
    rows = aggregate(run_crosswalk(inputs, fake), scf)
    by_id = {r["SCF Control ID"]: r for r in rows}
    assert by_id["GOV-01"]["Findings"] == 3
    assert by_id["GOV-01"]["Distinct Findings"] == 3
    assert by_id["GOV-01"]["Priority Score"] == 4.0  # 5 * (10+10+60)/100
    assert by_id["CRY-01"]["Priority Score"] == 4.75  # 5 * 95/100
    assert rows[0]["SCF Control ID"] == "CRY-01"
    assert by_id["GOV-01"]["Sample Model Justification"] == "best"
    assert by_id["GOV-01"]["Average Model Confidence (%)"] == 27
    assert by_id["GOV-01"]["Source Controls"] == ["X.0", "X.1", "X.2"]


def test_detail_rows_and_rejected():
    inputs = [CrosswalkInput("A", "a", "S3.1"), CrosswalkInput("B", "b")]
    fake = FakeMapper(
        {"a": [_mapped("CRY-01", 80)], "b": [_mapped("CRY-03", 40)]},
        rejected={"a": ["AC-2"], "b": ["AC-2", "SC-8"]},
    )
    results = run_crosswalk(inputs, fake)
    rows = detail_rows(results)
    assert [(r["Input"], r["Source Control"], r["SCF Control ID"]) for r in rows] == [
        ("A", "S3.1", "CRY-01"),
        ("B", "", "CRY-03"),
    ]
    assert all_rejected(results) == ["AC-2", "SC-8"]


def test_identical_findings_count_once_in_the_ranking():
    """A control failing on many resources must not outrank by volume alone."""
    many = [CrosswalkInput(f"F{i}", "same text", "S3.1") for i in range(100)]
    one = [CrosswalkInput("G", "other text", "IAM.6")]
    fake = FakeMapper(
        {"same text": [_mapped("DCH-01", 40)], "other text": [_mapped("IAC-06", 90)]}
    )
    rows = aggregate(run_crosswalk(many + one, fake), {})
    by_id = {r["SCF Control ID"]: r for r in rows}
    assert by_id["DCH-01"]["Findings"] == 100
    assert by_id["DCH-01"]["Distinct Findings"] == 1
    assert by_id["DCH-01"]["Priority Score"] == 0.4
    assert rows[0]["SCF Control ID"] == "IAC-06"


def test_capped_ids_are_carried_through():
    class Capped:
        def __call__(self, text, top_k):
            return MappingResult(
                mappings=[_mapped("CRY-01", 90)], capped_control_ids=["GOV-01"]
            )

    [r] = run_crosswalk([CrosswalkInput("A", "a")], Capped())
    assert r.capped == ["GOV-01"]
