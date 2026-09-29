"""
Measure retrieval (and optionally the model step) against a gold set.

The gold set is built without hand labeling, from two published mappings:

1. AWS's mapping of each Security Hub control to NIST SP 800-53 rev 5, as
   returned in `RelatedRequirements` by
   `aws securityhub describe-standards-controls`.
2. SCF's own crosswalk from its controls to NIST SP 800-53 (a column of the
   SCF workbook, kept in data/scf_parsed.json).

A Security Hub control's gold SCF controls are the SCF controls whose 800-53
column lists any of its 800-53 requirements. This is a transitive label: it
says the SCF control and the finding share an 800-53 requirement, not that a
reviewer judged the pair. Treat the numbers as a consistency check against
two published mappings, not as ground-truth accuracy.
"""

import csv
import math
import re
import statistics
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field

import numpy as np

_NIST_PREFIX = re.compile(r"^NIST\.800-53\.r5\s+", re.IGNORECASE)
_NIST_TOKEN = re.compile(r"[A-Z]{2}-\d+(?:\(\d+\))?")
_NIST_PARTS = re.compile(r"([A-Z]{2})-(\d+)(?:\((\d+)\))?")


def canonical_nist(ref: str) -> str:
    """
    One spelling per 800-53 control: 'AC-02(01)' and 'AC-2(1)' -> 'AC-2(1)'.

    AWS writes 800-53 IDs without leading zeros; the SCF workbook (2026.3)
    zero-pads them. Without this, most pairs would silently fail to match.
    """
    m = _NIST_PARTS.fullmatch(ref.strip().upper())
    if not m:
        return ref.strip().upper()
    family, number, enhancement = m.groups()
    out = f"{family}-{int(number)}"
    return f"{out}({int(enhancement)})" if enhancement is not None else out


@dataclass
class GoldCase:
    case_id: str
    text: str
    gold: set[str]
    nist_refs: list[str]


def nist_800_53_column(
    scf_data: list[dict], preferred: str | None = None
) -> str | None:
    """The SCF crosswalk column for NIST SP 800-53 rev 5 (or `preferred` if given)."""
    columns = sorted({col for c in scf_data for col in (c.get("regulations") or {})})
    if preferred:
        return preferred if preferred in columns else None
    # 800-53B columns are baselines (low/moderate/high/privacy), not the full catalog.
    candidates = [
        c for c in columns if "800-53" in c and "800-53b" not in c.lower()
    ] or [c for c in columns if "800-53" in c]
    for col in candidates:
        compact = col.lower().replace(" ", "")
        if "r5" in compact or "rev5" in compact:
            return col
    return candidates[0] if candidates else None


def nist_refs(related_requirements: Iterable[str]) -> list[str]:
    """800-53 rev 5 IDs from Security Hub RelatedRequirements, e.g. 'NIST.800-53.r5 AC-3(7)' -> 'AC-3(7)'."""
    refs = []
    for req in related_requirements:
        if _NIST_PREFIX.match(req):
            ref = _NIST_PREFIX.sub("", req).strip().upper()
            if _NIST_TOKEN.fullmatch(ref):
                ref = canonical_nist(ref)
                if ref not in refs:
                    refs.append(ref)
    return refs


def scf_index_by_nist(scf_data: list[dict], column: str) -> dict[str, set[str]]:
    """800-53 ID -> SCF control IDs whose crosswalk cell lists it."""
    index: dict[str, set[str]] = {}
    for control in scf_data:
        cell = (control.get("regulations") or {}).get(column, "")
        for ref in _NIST_TOKEN.findall(str(cell).upper()):
            index.setdefault(canonical_nist(ref), set()).add(control["control_id"])
    return index


def build_gold_set(
    standards_controls: list[dict], scf_data: list[dict], column: str
) -> list[GoldCase]:
    """
    One case per Security Hub control that has at least one gold SCF control.

    `standards_controls` is the `StandardsControls` list from
    `aws securityhub describe-standards-controls`.
    """
    index = scf_index_by_nist(scf_data, column)
    cases = []
    for sc in standards_controls:
        refs = nist_refs(sc.get("RelatedRequirements") or [])
        gold = set().union(*(index.get(r, set()) for r in refs)) if refs else set()
        if not gold:
            continue
        text = f"Title: {sc.get('Title', '')}\nDescription: {sc.get('Description', '')}"
        cases.append(
            GoldCase(
                case_id=str(sc.get("ControlId", "")),
                text=text.strip(),
                gold=gold,
                nist_refs=refs,
            )
        )
    return cases


def write_gold_csv(cases: list[GoldCase], path: str) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["case_id", "text", "gold_scf_ids", "nist_800_53"])
        for c in cases:
            writer.writerow(
                [c.case_id, c.text, " ".join(sorted(c.gold)), " ".join(c.nist_refs)]
            )


def read_gold_csv(path: str) -> list[GoldCase]:
    with open(path, encoding="utf-8", newline="") as f:
        return [
            GoldCase(
                case_id=row["case_id"],
                text=row["text"],
                gold=set(row["gold_scf_ids"].split()),
                nist_refs=row.get("nist_800_53", "").split(),
            )
            for row in csv.DictReader(f)
        ]


@dataclass
class GoldSetStats:
    controls: int  # Security Hub controls read
    no_nist: int  # dropped: no NIST 800-53 rev 5 requirement
    no_scf: int  # dropped: has 800-53 requirements, but SCF maps none of them
    cases: int
    median_gold: float
    max_gold: int
    small_cases: int  # cases with at most SMALL_GOLD gold controls


SMALL_GOLD = 10


def gold_set_stats(
    standards_controls: list[dict], cases: list[GoldCase]
) -> GoldSetStats:
    """How many controls became cases, why the rest were dropped, and gold-set sizes."""
    no_nist = sum(
        1
        for sc in standards_controls
        if not nist_refs(sc.get("RelatedRequirements") or [])
    )
    sizes = [len(c.gold) for c in cases]
    return GoldSetStats(
        controls=len(standards_controls),
        no_nist=no_nist,
        no_scf=len(standards_controls) - no_nist - len(cases),
        cases=len(cases),
        median_gold=statistics.median(sizes) if sizes else 0.0,
        max_gold=max(sizes, default=0),
        small_cases=sum(1 for n in sizes if n <= SMALL_GOLD),
    )


# --- AWS Security Hub user guide (awsdocs markdown) ------------------------------

_MD_ANCHOR = re.compile(r"<a name=\"[^\"]*\"></a>")
_MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_MD_ESCAPE = re.compile(r"\\(.)")
_CONTROL_HEADING = re.compile(r"^## \[([A-Za-z0-9]+\.\d+)\]\s*(.*)$")
_FIELD = re.compile(r"^\*\*([^*]+?)\*\*\s*(.*)$")


def markdown_to_text(line: str) -> str:
    """Plain text from one line of awsdocs markdown: no anchors, links, escapes or emphasis."""
    line = _MD_ANCHOR.sub("", line)
    line = _MD_ESCAPE.sub(lambda m: m.group(1), line)
    line = _MD_LINK.sub(lambda m: m.group(1).strip(), line)
    line = line.replace("`", "").replace("*", "")
    return " ".join(line.split())


def parse_awsdocs_controls(markdown: str) -> list[dict]:
    """
    Security Hub controls from one control-reference page of the AWS Security
    Hub user guide (awsdocs/aws-security-hub-user-guide, doc_source/*-controls.md).

    Each control is a `## \\[ID\\] Title` section with bold fields such as
    `**Related requirements:** NIST.800-53.r5 AC-2, ...`, followed by prose.
    Returns dicts in the `describe-standards-controls` shape (ControlId, Title,
    Description, RelatedRequirements). The description is the section's first
    prose paragraph, which approximates the API's one-paragraph Description.
    """
    controls: list[dict] = []
    current: dict | None = None
    paragraph: list[str] = []
    in_subsection = False

    def close_paragraph() -> None:
        if current is not None and paragraph and not current["Description"]:
            current["Description"] = " ".join(paragraph)
        paragraph.clear()

    for raw in markdown.splitlines():
        line = raw.strip()
        if line.startswith(("# ", "## ")):
            close_paragraph()
            current, in_subsection = None, False
            heading = _CONTROL_HEADING.match(markdown_to_text(line))
            if heading and line.startswith("## "):
                current = {
                    "ControlId": heading.group(1),
                    "Title": heading.group(2).strip(),
                    "Description": "",
                    "RelatedRequirements": [],
                }
                controls.append(current)
            continue
        if current is None or in_subsection:
            continue
        if line.startswith("#"):  # ### Remediation and deeper: not the description
            close_paragraph()
            in_subsection = True
            continue
        if not line:
            close_paragraph()
            continue
        field = _FIELD.match(line)
        if field or line.startswith(("+", "|", "<", "`", "!")):
            close_paragraph()
            name = field.group(1).strip().rstrip(":").lower() if field else ""
            if field and name == "related requirements":
                parts = (markdown_to_text(p) for p in field.group(2).split(","))
                current["RelatedRequirements"] = [p for p in parts if p]
            continue
        if not current["Description"]:
            paragraph.append(markdown_to_text(line))
    close_paragraph()
    return controls


# --- Retrieval scoring -----------------------------------------------------------


@dataclass
class RetrievalScores:
    k: int
    cases: int
    hit_rate: float  # share of cases with at least one gold control in the top k
    mean_recall: float  # mean share of each case's gold controls in the top k
    mrr: float = 0.0  # mean reciprocal rank of the first gold control (0 beyond k)


def first_gold_rank(gold: set[str], ranking: Sequence[str]) -> int | None:
    """1-based rank of the first gold control in `ranking`, or None."""
    for i, control_id in enumerate(ranking, start=1):
        if control_id in gold:
            return i
    return None


def scores_from_rankings(
    cases: list[GoldCase], ranked: list[list[str]], ks: Iterable[int]
) -> list[RetrievalScores]:
    """Hit rate, mean recall and MRR at each k, from one ranking per case (same order)."""
    scores = []
    for k in sorted(ks):
        hits, recalls, reciprocal = 0, 0.0, 0.0
        for c, ranking in zip(cases, ranked):
            top = ranking[:k]
            found = len(c.gold & set(top))
            hits += found > 0
            recalls += found / len(c.gold)
            rank = first_gold_rank(c.gold, top)
            reciprocal += 1 / rank if rank else 0.0
        n = len(cases) or 1
        scores.append(
            RetrievalScores(k, len(cases), hits / n, recalls / n, reciprocal / n)
        )
    return scores


def score_retrieval(
    cases: list[GoldCase],
    retrieve: Callable[[str, int], list[str]],
    ks: Iterable[int] = (10, 50),
) -> list[RetrievalScores]:
    """Score `retrieve(text, k) -> ranked control IDs` at each k (one call at max k)."""
    ks = sorted(ks)
    # Keyed by position, so duplicate or empty case IDs never merge cases.
    ranked = [retrieve(c.text, ks[-1]) for c in cases]
    return scores_from_rankings(cases, ranked, ks)


def random_hit_probability(corpus: int, gold: int, k: int) -> float:
    """P(a uniformly random k-subset of `corpus` controls holds at least one of `gold`)."""
    if gold <= 0 or k <= 0:
        return 0.0
    if k > corpus - gold:
        return 1.0
    return 1.0 - math.comb(corpus - gold, k) / math.comb(corpus, k)


def random_expected_mrr(corpus: int, gold: int, k: int) -> float:
    """E[1 / rank of the first gold control] for a random ranking, counting 0 beyond k."""
    if gold <= 0 or corpus <= 0:
        return 0.0
    total = math.comb(corpus, gold)
    # P(first gold control at rank r) = C(corpus - r, gold - 1) / C(corpus, gold)
    return sum(
        math.comb(corpus - r, gold - 1) / total / r
        for r in range(1, min(k, corpus) + 1)
    )


def random_baseline(
    cases: list[GoldCase], corpus: int, ks: Iterable[int]
) -> list[RetrievalScores]:
    """
    The exact expected scores of a retriever that ranks the `corpus` controls
    at random, given each case's gold-set size. Large gold sets make a high
    hit rate cheap; this is the floor to compare against.
    """
    scores = []
    n = len(cases) or 1
    for k in sorted(ks):
        hit = sum(random_hit_probability(corpus, len(c.gold), k) for c in cases)
        mrr = sum(random_expected_mrr(corpus, len(c.gold), k) for c in cases)
        recall = min(k, corpus) / corpus if corpus and cases else 0.0
        scores.append(RetrievalScores(k, len(cases), hit / n, recall, mrr / n))
    return scores


def tfidf_retriever(
    control_ids: list[str], control_texts: list[str]
) -> Callable[[str, int], list[str]]:
    """
    A lexical baseline over the same control texts the embedding retriever
    sees: TF-IDF (English stop words, sublinear tf, unigrams and bigrams)
    ranked by cosine similarity.
    """
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import linear_kernel

    vectorizer = TfidfVectorizer(
        stop_words="english", sublinear_tf=True, ngram_range=(1, 2)
    )
    matrix = vectorizer.fit_transform(control_texts)

    def retrieve(text: str, k: int) -> list[str]:
        similarities = linear_kernel(vectorizer.transform([text]), matrix).ravel()
        # Stable sort on the negated score: ties keep catalog order.
        order = np.argsort(-similarities, kind="stable")[:k]
        return [control_ids[i] for i in order]

    return retrieve


def comparison_markdown(methods: dict[str, list[RetrievalScores]]) -> str:
    """One table, a row per k: hit rate, mean recall and MRR@k for each method."""
    names = list(methods)
    header = " | ".join(f"{n} hit rate | {n} recall | {n} MRR" for n in names)
    lines = [f"| k | {header} |", "|---:|" + "---:|---:|---:|" * len(names)]
    for i, first in enumerate(methods[names[0]] if names else []):
        cells = []
        for n in names:
            s = methods[n][i]
            cells += [f"{s.hit_rate:.1%}", f"{s.mean_recall:.1%}", f"{s.mrr:.3f}"]
        lines.append(f"| {first.k} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def write_per_case_csv(
    path: str,
    cases: list[GoldCase],
    rankings: dict[str, list[list[str]]],
    corpus: int,
    k: int,
) -> None:
    """
    One row per case, IDs and numbers only (no control text), so the file can
    be committed. A rank is 1-based within the top k and blank when no gold
    control is in the top k.
    """
    names = list(rankings)
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["case_id", "n_nist_refs", "n_gold"]
            + [f"first_gold_rank_{n}" for n in names]
            + [f"random_hit_probability_at_{k}"]
        )
        for i, c in enumerate(cases):
            ranks = [first_gold_rank(c.gold, rankings[n][i][:k]) for n in names]
            writer.writerow(
                [c.case_id, len(c.nist_refs), len(c.gold)]
                + ["" if r is None else r for r in ranks]
                + [f"{random_hit_probability(corpus, len(c.gold), k):.4f}"]
            )


@dataclass
class Suggestion:
    """What the pipeline returned for one input: the IDs it suggested and the
    IDs the model gave that validation rejected (not in SCF or not a candidate)."""

    ids: list[str]
    rejected: list[str] = field(default_factory=list)


@dataclass
class ModelCase:
    case_id: str
    suggested: list[str]
    rejected: list[str]
    correct: int
    failed: bool = False
    error: str = ""  # exception class and message when the call failed


@dataclass
class ModelScores:
    cases: int
    precision: float  # share of suggested controls that are gold
    hit_rate: float  # share of cases with at least one gold suggestion
    empty: int  # cases with no suggestion (nothing returned, or all rejected)
    errors: int = 0  # cases where the call failed (after retries)
    rejected: int = 0  # IDs the model returned that validation dropped
    cases_with_rejections: int = 0
    per_case: list[ModelCase] = field(default_factory=list, repr=False)


def score_model(
    cases: list[GoldCase], suggest: Callable[[str], "list[str] | Suggestion"]
) -> ModelScores:
    """
    Score `suggest(text)` (the full pipeline), which returns the suggested
    control IDs, or a Suggestion that also carries the rejected IDs.

    A failed call is counted in `errors` and does not stop the run; errors
    and empty answers both count as misses in `hit_rate`.
    """
    suggested_total, correct_total, hits, empty, errors = 0, 0, 0, 0, 0
    rejected_total, cases_with_rejections = 0, 0
    per_case = []
    for c in cases:
        try:
            answer = suggest(c.text)
        except Exception as e:  # one failing case must not lose the whole run
            errors += 1
            error = f"{type(e).__name__}: {e}"[:300]
            per_case.append(ModelCase(c.case_id, [], [], 0, failed=True, error=error))
            continue
        if isinstance(answer, Suggestion):
            ids, rejected = answer.ids, answer.rejected
        else:
            ids, rejected = answer, []
        rejected_total += len(rejected)
        cases_with_rejections += bool(rejected)
        correct = len(set(ids) & c.gold)
        per_case.append(ModelCase(c.case_id, list(ids), list(rejected), correct))
        if not ids:
            empty += 1
            continue
        suggested_total += len(ids)
        correct_total += correct
        hits += correct > 0
    n = len(cases) or 1
    return ModelScores(
        cases=len(cases),
        precision=correct_total / suggested_total if suggested_total else 0.0,
        hit_rate=hits / n,
        empty=empty,
        errors=errors,
        rejected=rejected_total,
        cases_with_rejections=cases_with_rejections,
        per_case=per_case,
    )


def write_per_case_model_csv(path: str, scores: ModelScores) -> None:
    """One row per case, IDs and counts only, so the file can be committed."""
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "case_id",
                "suggested",
                "n_gold_suggested",
                "rejected",
                "call_failed",
                "error_type",
            ]
        )
        for m in scores.per_case:
            writer.writerow(
                [
                    m.case_id,
                    " ".join(m.suggested),
                    m.correct,
                    " ".join(m.rejected),
                    int(m.failed),
                    m.error.split(":", 1)[0],
                ]
            )


def results_markdown(
    retrieval: list[RetrievalScores],
    model: ModelScores | None,
    scf_release: str | None,
    column: str | None,
    llm_name: str | None = None,
) -> str:
    lines = [
        f"SCF release: {scf_release or 'not recorded'}; 800-53 column: {column or 'n/a'}; "
        f"cases: {retrieval[0].cases if retrieval else 0}",
        "",
        "| Stage | Metric | Value |",
        "|---|---|---|",
    ]
    for s in retrieval:
        lines.append(f"| Retrieval | Hit rate @{s.k} | {s.hit_rate:.1%} |")
        lines.append(f"| Retrieval | Mean recall @{s.k} | {s.mean_recall:.1%} |")
        lines.append(f"| Retrieval | MRR @{s.k} | {s.mrr:.3f} |")
    if model is not None:
        label = f"Model ({llm_name})" if llm_name else "Model"
        lines.append(f"| {label} | Precision of suggestions | {model.precision:.1%} |")
        lines.append(
            f"| {label} | Hit rate (≥1 gold suggestion) | {model.hit_rate:.1%} |"
        )
        lines.append(f"| {label} | Cases with no suggestion | {model.empty} |")
        lines.append(f"| {label} | Cases where the call failed | {model.errors} |")
        lines.append(f"| {label} | IDs rejected by validation | {model.rejected} |")
        lines.append(
            f"| {label} | Cases with a rejected ID | {model.cases_with_rejections} |"
        )
    return "\n".join(lines) + "\n"
