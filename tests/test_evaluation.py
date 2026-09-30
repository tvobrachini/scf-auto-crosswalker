import csv
import itertools
import json

import pytest

from evaluation import (
    GoldCase,
    Suggestion,
    build_gold_set,
    canonical_nist,
    comparison_markdown,
    error_summary,
    first_gold_rank,
    gold_set_stats,
    markdown_to_text,
    nist_800_53_column,
    nist_refs,
    parse_awsdocs_controls,
    random_baseline,
    random_expected_mrr,
    random_hit_probability,
    read_gold_csv,
    results_markdown,
    score_model,
    score_retrieval,
    scores_from_rankings,
    tfidf_retriever,
    write_gold_csv,
    write_per_case_csv,
    write_per_case_model_csv,
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
    # SCF 2026.3 column names: the full catalog, not a rev 4 or 800-53B baseline.
    scf_2026 = [
        {
            "control_id": "A-01",
            "regulations": {
                "NIST 800-53 R4": "AC-01",
                "NIST 800-53A R5 (high)": "AC-01",
                "NIST 800-53B R5 (high)": "AC-01",
                "NIST 800-53 R5.2": "AC-01",
            },
        }
    ]
    assert nist_800_53_column(scf_2026) == "NIST 800-53 R5.2"
    baselines_only = [{"control_id": "A-01", "regulations": {"NIST 800-53B": "x"}}]
    assert nist_800_53_column(baselines_only) == "NIST 800-53B"


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
    assert m.errors == 0


def test_score_model_survives_failing_calls():
    cases = [GoldCase("a", "ta", {"X-01"}, []), GoldCase("b", "tb", {"Y-01"}, [])]

    def suggest(text):
        if text == "ta":
            raise RuntimeError("429 after retries")
        return ["Y-01"]

    m = score_model(cases, suggest)
    assert m.errors == 1
    assert m.per_case[0].error == "RuntimeError: 429 after retries"
    assert m.hit_rate == 0.5
    assert m.precision == 1.0


def test_score_model_counts_rejected_ids(tmp_path):
    cases = [
        GoldCase("a", "ta", {"X-01"}, []),
        GoldCase("b", "tb", {"Y-01"}, []),
        GoldCase("c", "tc", {"Z-01"}, []),
    ]
    answers = {
        "ta": Suggestion(["X-01"], ["AC-1", "SC-8"]),
        "tb": Suggestion([], ["NOPE-99"]),  # every ID rejected: an empty case
        "tc": ["Z-01"],  # a plain list still works
    }
    m = score_model(cases, lambda t: answers[t])
    assert (m.rejected, m.cases_with_rejections, m.empty) == (3, 2, 1)
    assert m.precision == 1.0
    assert m.hit_rate == pytest.approx(2 / 3)

    path = tmp_path / "per_case_model.csv"
    write_per_case_model_csv(str(path), m)
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    assert [r["rejected"] for r in rows] == ["AC-1 SC-8", "NOPE-99", ""]
    assert [r["n_gold_suggested"] for r in rows] == ["1", "0", "1"]
    md = results_markdown([], m, None, None)
    assert "| Model | IDs rejected by validation | 3 |" in md
    assert "| Model | Cases with a rejected ID | 2 |" in md


def test_error_summary_groups_by_cause_and_drops_urls():
    cases = [GoldCase(str(i), f"t{i}", {"X-01"}, []) for i in range(3)]
    tokens = {"t0": 115158, "t1": 114594}

    def suggest(text):
        if text in tokens:
            raise RuntimeError(
                f"402: requested up to {tokens[text]} tokens. "
                "To increase, visit https://openrouter.ai/workspaces/default/keys/abc123"
            )
        raise ValueError("bad schema")

    m = score_model(cases, suggest)
    summary = error_summary(m)
    assert [count for count, _ in summary] == [2, 1]
    assert "openrouter.ai" not in summary[0][1] and "<url>" in summary[0][1]
    md = results_markdown([], m, None, None)
    assert md.startswith("**3 of 3 model calls failed;")


def test_score_retrieval_keeps_duplicate_case_ids_apart():
    cases = [GoldCase("", "ta", {"X-01"}, []), GoldCase("", "tb", {"Y-01"}, [])]
    ranking = {"ta": ["X-01"], "tb": ["Z-01"]}
    [s] = score_retrieval(cases, lambda t, k: ranking[t], ks=(1,))
    assert s.hit_rate == 0.5


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
    assert "dropped without a NIST 800-53 rev 5 requirement: 1" in results
    assert "## All cases (2)" in results
    assert "random (expected) hit rate" in results
    per_case = list(csv.DictReader((tmp_path / "per_case_retrieval.csv").open()))
    assert [r["case_id"] for r in per_case] == ["CloudFront.3", "IAM.6"]
    assert set(per_case[0]) >= {"first_gold_rank_embedding", "first_gold_rank_tfidf"}

    assert run_eval.main(["--controls", str(controls), "--column", "Typo"]) == 1

    # --onnx-model swaps in the ONNX encoder and its own embeddings cache file.
    import onnx_encoder

    (tmp_path / "model.onnx").write_bytes(b"fake")
    monkeypatch.setattr(mapper, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(onnx_encoder, "load_onnx_encoder", lambda d: fake_embeddings)
    gold = str(tmp_path / "gold.csv")
    # A model.onnx other than the pinned one is refused unless asked for.
    with pytest.raises(SystemExit, match="not the pinned"):
        run_eval.main(["--gold", gold, "--onnx-model", str(tmp_path)])
    assert (
        run_eval.main(
            ["--gold", gold, "--onnx-model", str(tmp_path), "--allow-unverified-onnx"]
        )
        == 0
    )
    assert mapper.EMBEDDINGS_CACHE_FILE.endswith("scf_embeddings_onnx.npz")
    assert mapper._get_embedding_model() is fake_embeddings
    results = (tmp_path / "results.md").read_text()
    assert "ONNX export (model.onnx sha256 " in results
    assert "## Gold set" not in results  # stats need the controls file


def test_run_eval_cli_openrouter_model(monkeypatch, tmp_path, fake_embeddings):
    """--llm --openrouter-model runs the app's pipeline on that model."""
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
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    gold = tmp_path / "gold.csv"
    write_gold_csv(
        [GoldCase("CloudFront.3", "text", {"CRY-01"}, ["SC-8(1)"])], str(gold)
    )

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert run_eval.main(["--gold", str(gold), "--llm", "--openrouter-model", "m"]) == 0
    results = (tmp_path / "results.md").read_text()
    assert "| Model" not in results  # skipped: no OPENROUTER_API_KEY

    from mapper import MappedControl, MappingResult

    seen_models = []

    def fake_map_text_to_scf(text, top_k=3):
        # The app's own pipeline is called, with the model set for this run.
        seen_models.append(os.environ.get("OPENROUTER_MODEL"))
        return MappingResult(
            mappings=[
                MappedControl(control_id="CRY-01", confidence=90, justification="j")
            ],
            rejected_control_ids=["SC-8"],
        )

    monkeypatch.setattr(run_eval, "map_text_to_scf", fake_map_text_to_scf)
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "fake-openrouter-key")
    assert (
        run_eval.main(
            [
                "--gold",
                str(gold),
                "--llm",
                "--openrouter-model",
                "openrouter/some-model",
            ]
        )
        == 0
    )
    assert seen_models == ["openrouter/some-model"]
    results = (tmp_path / "results.md").read_text()
    assert "Model (openrouter/some-model (OpenRouter))" in results
    assert "Precision of suggestions | 100.0%" in results
    assert "IDs rejected by validation | 1 |" in results
    per_case = (tmp_path / "per_case_model.csv").read_text(encoding="utf-8")
    assert per_case.splitlines()[1] == "CloudFront.3,CRY-01,1,SC-8,0,"


def test_run_eval_refuses_demo_mode(monkeypatch, tmp_path):
    import importlib.util
    import os

    spec = importlib.util.spec_from_file_location(
        "run_eval_demo",
        os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "scripts", "run_eval.py"
        ),
    )
    run_eval = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(run_eval)
    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    assert run_eval.main(["--gold", str(tmp_path / "gold.csv")]) == 1


# --- 800-53 ID spelling -----------------------------------------------------------


def test_canonical_nist_drops_zero_padding():
    assert canonical_nist("AC-02(01)") == "AC-2(1)"
    assert canonical_nist("sc-08") == "SC-8"
    assert canonical_nist("PM-10") == "PM-10"
    assert canonical_nist("not an id") == "NOT AN ID"


def test_zero_padded_scf_cells_match_aws_ids():
    """SCF 2026.3 writes 'AC-02(01)'; AWS writes 'AC-2(1)'. They must match."""
    scf = [
        {"control_id": "IAC-01", "regulations": {COL: "AC-02(01)\nIA-02"}},
        {"control_id": "IAC-02", "regulations": {COL: "AC-02"}},
    ]
    controls = [
        {
            "ControlId": "IAM.1",
            "RelatedRequirements": ["NIST.800-53.r5 AC-2(1)", "NIST.800-53.r5 IA-2"],
        }
    ]
    [case] = build_gold_set(controls, scf, COL)
    assert case.gold == {"IAC-01"}
    assert case.nist_refs == ["AC-2(1)", "IA-2"]


def test_gold_set_stats():
    cases = build_gold_set(CONTROLS, SCF, COL)
    unmapped = {"ControlId": "Y.1", "RelatedRequirements": ["NIST.800-53.r5 PE-9"]}
    stats = gold_set_stats(CONTROLS + [unmapped], cases)
    assert (stats.controls, stats.no_nist, stats.no_scf, stats.cases) == (4, 1, 1, 2)
    assert (stats.median_gold, stats.max_gold, stats.small_cases) == (2, 3, 2)
    empty = gold_set_stats([], [])
    assert (empty.median_gold, empty.max_gold) == (0.0, 0)


# --- awsdocs markdown -------------------------------------------------------------

# Synthetic page in the layout of doc_source/*-controls.md (not AWS text).
AWSDOCS_PAGE = r"""# Widget controls<a name="widget-controls"></a>

These controls are about widgets\.

## \[Widget\.1\] Widgets should be \(very\) shiny<a name="widget-1"></a>

**Related requirements:** PCI DSS v3\.2\.1/1\.2\.1,PCI DSS v3\.2\.1/2\.1, NIST\.800\-53\.r5 AC\-2\(1\), NIST\.800\-53\.r5 SC\-8

**Category:** Protect > Shine

**Severity:** Medium

**Resource type:** `AWS::Widget::Thing`

**AWS Config rule:** [widget-shiny](https://example.com/widget-shiny)

**Parameters:**
+ `shineLevel`: 3

This control checks whether a widget is shiny\. See the [widget guide](https://example.com/guide)
for *details*\.

A second paragraph that is not part of the description\.

**Note**
Not in the description either\.

### Remediation<a name="widget-1-remediation"></a>

Polish the widget\.

## \[Widget\.2\] Widgets without NIST mapping<a name="widget-2"></a>

**Related requirements:** CIS Widget Benchmark v1\.0/1\.1

**Severity:** Low

Checks something else\.

## Some other heading<a name="other"></a>

**Related requirements:** NIST\.800\-53\.r5 AC\-1

Not a control\.
"""


def test_markdown_to_text():
    assert (
        markdown_to_text(r"See \[the\] [guide](https://x.y/z) for *more* `code`\.")
        == "See [the] guide for more code."
    )


def test_parse_awsdocs_controls():
    controls = parse_awsdocs_controls(AWSDOCS_PAGE)
    assert [c["ControlId"] for c in controls] == ["Widget.1", "Widget.2"]
    w1, w2 = controls
    assert w1["Title"] == "Widgets should be (very) shiny"
    assert w1["Description"] == (
        "This control checks whether a widget is shiny. "
        "See the widget guide for details."
    )
    assert w1["RelatedRequirements"] == [
        "PCI DSS v3.2.1/1.2.1",
        "PCI DSS v3.2.1/2.1",
        "NIST.800-53.r5 AC-2(1)",
        "NIST.800-53.r5 SC-8",
    ]
    assert nist_refs(w1["RelatedRequirements"]) == ["AC-2(1)", "SC-8"]
    assert w2["Description"] == "Checks something else."
    assert nist_refs(w2["RelatedRequirements"]) == []


def test_parse_awsdocs_controls_without_description():
    [c] = parse_awsdocs_controls("## \\[X\\.1\\] Title only\n\n**Severity:** Low\n")
    assert (c["ControlId"], c["Description"], c["RelatedRequirements"]) == (
        "X.1",
        "",
        [],
    )


def test_import_awsdocs_controls_script(tmp_path):
    import importlib.util
    import os

    spec = importlib.util.spec_from_file_location(
        "import_awsdocs_controls",
        os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "scripts",
            "import_awsdocs_controls.py",
        ),
    )
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)

    repo = tmp_path / "repo"
    assert script.main(["--repo", str(repo)]) == 1  # no doc_source/
    (repo / "doc_source").mkdir(parents=True)
    assert script.main(["--repo", str(repo)]) == 1  # no control pages
    (repo / "doc_source" / "widget-controls.md").write_text(AWSDOCS_PAGE)
    (repo / "doc_source" / "zz-controls.md").write_text(
        "## \\[Widget\\.1\\] Duplicate\n\nText\\.\n"
    )
    (repo / "doc_source" / "index.md").write_text(AWSDOCS_PAGE)  # not a control page
    out = tmp_path / "controls.json"
    assert script.main(["--repo", str(repo), "--out", str(out)]) == 0
    data = json.loads(out.read_text())
    assert data["Source"]["repo"].endswith("aws-security-hub-user-guide")
    controls = data["StandardsControls"]
    assert [c["ControlId"] for c in controls] == ["Widget.1", "Widget.2"]
    assert controls[0]["Title"] == "Widgets should be (very) shiny"  # first kept
    assert controls[0]["SourceFile"] == "widget-controls.md"


# --- Ranking metrics and baselines -------------------------------------------------


def test_first_gold_rank():
    assert first_gold_rank({"B"}, ["A", "B", "C"]) == 2
    assert first_gold_rank({"Z"}, ["A", "B"]) is None


def test_scores_from_rankings_mrr():
    cases = [GoldCase("a", "", {"X"}, []), GoldCase("b", "", {"Y", "Z"}, [])]
    ranked = [["X", "Q"], ["Q", "Z", "Y"]]
    s1, s3 = scores_from_rankings(cases, ranked, (3, 1))
    assert (s1.k, s1.hit_rate, s1.mrr) == (1, 0.5, 0.5)
    assert s3.mrr == pytest.approx((1 + 1 / 2) / 2)
    assert s3.mean_recall == 1.0


def _brute_force_random(corpus, gold, k):
    """Exact expectations by enumerating every ranking of a tiny corpus."""
    hits, reciprocal, n = 0, 0.0, 0
    gold_ids = set(range(gold))
    for perm in itertools.permutations(range(corpus)):
        n += 1
        rank = first_gold_rank(gold_ids, perm[:k])
        hits += rank is not None
        reciprocal += 1 / rank if rank else 0.0
    return hits / n, reciprocal / n


@pytest.mark.parametrize("corpus,gold,k", [(5, 1, 1), (5, 2, 2), (6, 3, 2), (6, 2, 5)])
def test_random_expectations_match_brute_force(corpus, gold, k):
    hit, mrr = _brute_force_random(corpus, gold, k)
    assert random_hit_probability(corpus, gold, k) == pytest.approx(hit)
    assert random_expected_mrr(corpus, gold, k) == pytest.approx(mrr)


def test_random_edge_cases():
    assert random_hit_probability(10, 0, 5) == 0.0
    assert random_hit_probability(10, 3, 8) == 1.0  # only 7 non-gold controls
    assert random_expected_mrr(10, 0, 5) == 0.0
    [s] = random_baseline([GoldCase("a", "", {"X"}, [])], 1591, (50,))
    assert s.hit_rate == pytest.approx(50 / 1591)
    assert s.mean_recall == pytest.approx(50 / 1591)
    [empty] = random_baseline([], 1591, (50,))
    assert (empty.cases, empty.hit_rate, empty.mean_recall) == (0, 0.0, 0.0)


def test_tfidf_retriever_ranks_the_lexical_match_first():
    retrieve = tfidf_retriever(
        ["A-01", "B-01", "C-01"],
        [
            "A-01 Governance: security program charter",
            "B-01 Crypto: encrypt data in transit with TLS",
            "C-01 Identity: multi-factor authentication for users",
        ],
    )
    assert retrieve("Require TLS to encrypt traffic in transit", 2)[0] == "B-01"
    assert len(retrieve("nothing in common", 3)) == 3


def test_comparison_markdown_and_per_case_csv(tmp_path):
    cases = [GoldCase("a", "", {"X"}, ["SC-8"]), GoldCase("b", "", {"Y", "Z"}, [])]
    rankings = {"emb": [["X", "Q"], ["Q", "Q2"]], "lex": [["Q", "X"], ["Z", "Q"]]}
    methods = {n: scores_from_rankings(cases, r, (1, 2)) for n, r in rankings.items()}
    md = comparison_markdown(methods)
    assert md.startswith("| k | emb hit rate | emb recall | emb MRR | lex hit rate")
    assert "| 1 | 50.0% | 50.0% | 0.500 | 50.0% | 25.0% | 0.500 |" in md
    assert comparison_markdown({}) == "| k |  |\n|---:|\n"

    path = tmp_path / "per_case.csv"
    write_per_case_csv(str(path), cases, rankings, 100, 2)
    rows = list(csv.DictReader(path.open()))
    assert rows[0] == {
        "case_id": "a",
        "n_nist_refs": "1",
        "n_gold": "1",
        "first_gold_rank_emb": "1",
        "first_gold_rank_lex": "2",
        "random_hit_probability_at_2": "0.0200",
    }
    assert rows[1]["first_gold_rank_emb"] == ""


def test_run_eval_suggestion_keeps_rejected_ids():
    import importlib.util
    import os

    from mapper import MappedControl, MappingResult

    spec = importlib.util.spec_from_file_location(
        "run_eval",
        os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "scripts", "run_eval.py"
        ),
    )
    run_eval = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(run_eval)

    result = MappingResult(
        mappings=[MappedControl(control_id="CRY-03", confidence=80, justification="j")],
        rejected_control_ids=["SC-8"],
    )
    assert run_eval._suggestion(result) == Suggestion(["CRY-03"], ["SC-8"])
    assert run_eval._suggestion(None) == Suggestion([])
