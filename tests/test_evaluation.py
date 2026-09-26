import json

import pytest

from evaluation import (
    GoldCase,
    build_gold_set,
    nist_800_53_column,
    nist_refs,
    read_gold_csv,
    results_markdown,
    score_model,
    score_retrieval,
    write_gold_csv,
)

COL = "NIST SP 800-53 R5"

SCF = [
    {"control_id": "CRY-03", "regulations": {COL: "SC-8\nSC-8(1)"}},
    {"control_id": "NET-12", "regulations": {COL: "SC-8"}},
    {"control_id": "IAC-06", "regulations": {COL: "IA-2(1)\nIA-2(2)"}},
    {"control_id": "GOV-01", "regulations": {"NIST SP 800-53 R4": "PM-1"}},
]

CONTROLS = [
    {
        "ControlId": "CloudFront.3",
        "Title": "CloudFront distributions should require encryption in transit",
        "Description": "Checks the viewer protocol policy.",
        "RelatedRequirements": ["NIST.800-53.r5 SC-8(1)", "PCI DSS 4.1"],
    },
    {
        "ControlId": "IAM.6",
        "Title": "Hardware MFA should be enabled for the root user",
        "Description": "Checks root MFA.",
        "RelatedRequirements": ["NIST.800-53.r5 IA-2(1)", "NIST.800-53.r5 SC-8"],
    },
    {
        "ControlId": "X.1",
        "Title": "No NIST mapping",
        "Description": "",
        "RelatedRequirements": ["CIS AWS Foundations 1.1"],
    },
]


def test_nist_refs_parsing():
    assert nist_refs(
        [
            "NIST.800-53.r5 AC-3(7)",
            "PCI DSS 7.2.1",
            "nist.800-53.r5 sc-8",
            "NIST.800-53.r5 AC-3(7)",
        ]
    ) == ["AC-3(7)", "SC-8"]


def test_column_detection():
    assert nist_800_53_column(SCF) == COL
    assert nist_800_53_column(SCF, "NIST SP 800-53 R4") == "NIST SP 800-53 R4"
    assert nist_800_53_column(SCF, "missing") is None
    assert nist_800_53_column([{"control_id": "A-01", "regulations": {}}]) is None


def test_build_gold_set_follows_both_mappings(tmp_path):
    cases = build_gold_set(CONTROLS, SCF, COL)
    by_id = {c.case_id: c for c in cases}
    assert set(by_id) == {"CloudFront.3", "IAM.6"}  # X.1 has no 800-53 mapping
    assert by_id["CloudFront.3"].gold == {"CRY-03"}
    assert by_id["IAM.6"].gold == {"IAC-06", "CRY-03", "NET-12"}
    assert by_id["CloudFront.3"].text.startswith("Title: CloudFront distributions")

    path = tmp_path / "gold.csv"
    write_gold_csv(cases, str(path))
    again = read_gold_csv(str(path))
    assert [(c.case_id, c.gold, c.nist_refs) for c in again] == [
        (c.case_id, c.gold, c.nist_refs) for c in cases
    ]


def test_score_retrieval():
    cases = [
        GoldCase("a", "ta", {"X-01", "X-02"}, []),
        GoldCase("b", "tb", {"Y-01"}, []),
    ]
    ranking = {"ta": ["X-01", "Z-01", "X-02"], "tb": ["Z-01", "Z-02", "Z-03"]}
    calls = []

    def retrieve(text, k):
        calls.append(k)
        return ranking[text][:k]

    s1, s3 = score_retrieval(cases, retrieve, ks=(3, 1))
    assert calls == [3, 3]  # one call per case, at the largest k
    assert (s1.k, s1.hit_rate, s1.mean_recall) == (1, 0.5, 0.25)
    assert (s3.k, s3.hit_rate, s3.mean_recall) == (3, 0.5, 0.5)


def test_score_model():
    cases = [
        GoldCase("a", "ta", {"X-01"}, []),
        GoldCase("b", "tb", {"Y-01"}, []),
        GoldCase("c", "tc", {"Z-01"}, []),
    ]
    answers = {"ta": ["X-01", "Q-01"], "tb": ["Q-02"], "tc": []}
    m = score_model(cases, lambda t: answers[t])
    assert m.precision == pytest.approx(1 / 3)
    assert m.hit_rate == pytest.approx(1 / 3)
    assert m.empty == 1


def test_results_markdown():
    cases = [GoldCase("a", "ta", {"X-01"}, [])]
    retrieval = score_retrieval(cases, lambda t, k: ["X-01"], ks=(10,))
    model = score_model(cases, lambda t: ["X-01"])
    md = results_markdown(retrieval, model, "SCF 2025.4", COL, "llama-3.1-8b-instant")
    assert "| Retrieval | Hit rate @10 | 100.0% |" in md
    assert "| Model (llama-3.1-8b-instant) | Precision of suggestions | 100.0% |" in md
    assert md.startswith("SCF release: SCF 2025.4")


def test_run_eval_cli_end_to_end(monkeypatch, tmp_path, fake_embeddings):
    """The CLI builds the gold set and scores retrieval, fully offline."""
    import importlib.util
    import os

    import mapper

    scf = [
        dict(c, domain="D", description=f"{c['control_id']} encrypt transit")
        for c in SCF
    ]
    monkeypatch.setattr(mapper, "load_scf_database", lambda: scf)
    spec = importlib.util.spec_from_file_location(
        "run_eval",
        os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "scripts", "run_eval.py"
        ),
    )
    run_eval = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(run_eval)
    monkeypatch.setattr(run_eval, "load_scf_database", lambda: scf)
    monkeypatch.setattr(run_eval, "EVAL_DIR", str(tmp_path))

    controls = tmp_path / "controls.json"
    controls.write_text(json.dumps({"StandardsControls": CONTROLS}))
    assert run_eval.main(["--controls", str(controls)]) == 0
    assert (tmp_path / "gold.csv").exists()
    results = (tmp_path / "results.md").read_text()
    assert "cases: 2" in results
    assert "Hit rate @50 | 100.0%" in results  # 4 controls, all retrieved at k=50
