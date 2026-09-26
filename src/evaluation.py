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
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass

_NIST_PREFIX = re.compile(r"^NIST\.800-53\.r5\s+", re.IGNORECASE)
_NIST_TOKEN = re.compile(r"[A-Z]{2}-\d+(?:\(\d+\))?")


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
    candidates = [c for c in columns if "800-53" in c]
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
            if _NIST_TOKEN.fullmatch(ref) and ref not in refs:
                refs.append(ref)
    return refs


def scf_index_by_nist(scf_data: list[dict], column: str) -> dict[str, set[str]]:
    """800-53 ID -> SCF control IDs whose crosswalk cell lists it."""
    index: dict[str, set[str]] = {}
    for control in scf_data:
        cell = (control.get("regulations") or {}).get(column, "")
        for ref in _NIST_TOKEN.findall(str(cell).upper()):
            index.setdefault(ref, set()).add(control["control_id"])
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
class RetrievalScores:
    k: int
    cases: int
    hit_rate: float  # share of cases with at least one gold control in the top k
    mean_recall: float  # mean share of each case's gold controls in the top k


def score_retrieval(
    cases: list[GoldCase],
    retrieve: Callable[[str, int], list[str]],
    ks: Iterable[int] = (10, 50),
) -> list[RetrievalScores]:
    """Score `retrieve(text, k) -> ranked control IDs` at each k (one call at max k)."""
    ks = sorted(ks)
    ranked = {c.case_id: retrieve(c.text, ks[-1]) for c in cases}
    scores = []
    for k in ks:
        hits, recalls = 0, 0.0
        for c in cases:
            top = set(ranked[c.case_id][:k])
            found = len(c.gold & top)
            hits += found > 0
            recalls += found / len(c.gold)
        n = len(cases) or 1
        scores.append(RetrievalScores(k, len(cases), hits / n, recalls / n))
    return scores


@dataclass
class ModelScores:
    cases: int
    precision: float  # share of suggested controls that are gold
    hit_rate: float  # share of cases with at least one gold suggestion
    empty: int  # cases where the model returned no valid control


def score_model(
    cases: list[GoldCase], suggest: Callable[[str], list[str]]
) -> ModelScores:
    """Score `suggest(text) -> suggested control IDs` (the full pipeline)."""
    suggested_total, correct_total, hits, empty = 0, 0, 0, 0
    for c in cases:
        ids = suggest(c.text)
        if not ids:
            empty += 1
            continue
        correct = len(set(ids) & c.gold)
        suggested_total += len(ids)
        correct_total += correct
        hits += correct > 0
    n = len(cases) or 1
    return ModelScores(
        cases=len(cases),
        precision=correct_total / suggested_total if suggested_total else 0.0,
        hit_rate=hits / n,
        empty=empty,
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
    if model is not None:
        label = f"Model ({llm_name})" if llm_name else "Model"
        lines.append(f"| {label} | Precision of suggestions | {model.precision:.1%} |")
        lines.append(
            f"| {label} | Hit rate (≥1 gold suggestion) | {model.hit_rate:.1%} |"
        )
        lines.append(f"| {label} | Cases with no valid suggestion | {model.empty} |")
    return "\n".join(lines) + "\n"
