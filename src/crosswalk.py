"""Run the crosswalk over one or many inputs and summarize the results."""

from collections.abc import Callable
from dataclasses import dataclass, field

from mapper import MappedControl, MappingResult

# Upper bound on findings mapped in one batch: each unique finding is one
# model call, run sequentially.
MAX_BATCH = 50


@dataclass
class CrosswalkInput:
    label: str  # shown to the user, e.g. "Finding 3" or the file name
    text: str  # what is embedded and sent to the model
    # The source control, when the input has one (a Security Hub control ID
    # such as "CloudFront.3"); used as the source of the OSCAL mapping.
    source_id: str | None = None


@dataclass
class CrosswalkResult:
    input: CrosswalkInput
    mappings: list[MappedControl] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    error: str | None = None


def run_crosswalk(
    inputs: list[CrosswalkInput],
    map_fn: Callable[[str, int], MappingResult | None],
    top_k: int = 3,
    on_progress: Callable[[int, int], None] | None = None,
) -> list[CrosswalkResult]:
    """
    Map every input with `map_fn(text, top_k)`.

    Inputs with identical text (common in Security Hub exports, where one
    control fails on many resources) are sent to the model once and share
    the result. An error on one input is recorded on it and does not stop
    the batch.
    """
    by_text: dict[str, CrosswalkResult] = {}
    results: list[CrosswalkResult] = []
    for i, item in enumerate(inputs):
        cached = by_text.get(item.text)
        if cached is None:
            cached = CrosswalkResult(input=item)
            try:
                mapped = map_fn(item.text, top_k)
                if mapped is None:
                    cached.error = "The SCF database is not available."
                else:
                    cached.mappings = list(mapped.mappings)
                    cached.rejected = list(mapped.rejected_control_ids)
            except Exception as e:  # reported per input in the UI
                cached.error = f"{type(e).__name__}: {e}"
            by_text[item.text] = cached
        results.append(
            CrosswalkResult(
                input=item,
                mappings=cached.mappings,
                rejected=cached.rejected,
                error=cached.error,
            )
        )
        if on_progress:
            on_progress(i + 1, len(inputs))
    return results


def unique_model_calls(inputs: list[CrosswalkInput]) -> int:
    return len({i.text for i in inputs})


def detail_rows(results: list[CrosswalkResult]) -> list[dict]:
    """One row per (input, suggested control), for the CSV export."""
    rows = []
    for r in results:
        for m in r.mappings:
            rows.append(
                {
                    "Input": r.input.label,
                    "Source Control": r.input.source_id or "",
                    "SCF Control ID": m.control_id,
                    "SCF Domain": m.domain,
                    "Control Description": m.description,
                    "Model Confidence (%)": m.confidence,
                    "Model Justification": m.justification,
                }
            )
    return rows


def aggregate(results: list[CrosswalkResult], scf_dict: dict[str, dict]) -> list[dict]:
    """
    Merge batch results per SCF control and rank them.

    Priority Score = SCF relative weight x sum of model confidences / 100,
    i.e. confidence-weighted hits, so ten 10%-confidence hits count the same
    as one 100%-confidence hit.
    """
    merged: dict[str, dict] = {}
    for r in results:
        for m in r.mappings:
            row = merged.setdefault(
                m.control_id,
                {
                    "SCF Control ID": m.control_id,
                    "SCF Domain": m.domain,
                    "Control Description": m.description,
                    "Weight": scf_dict.get(m.control_id, {}).get("weight", 1),
                    "Hit Count": 0,
                    "_confidence_sum": 0,
                    "_best": -1,
                    "Sample Model Justification": "",
                    "Source Controls": [],
                    "Regulations": m.regulations,
                },
            )
            row["Hit Count"] += 1
            row["_confidence_sum"] += m.confidence
            if m.confidence > row["_best"]:
                row["_best"] = m.confidence
                row["Sample Model Justification"] = m.justification
            source = r.input.source_id or r.input.label
            if source not in row["Source Controls"]:
                row["Source Controls"].append(source)

    rows = []
    for row in merged.values():
        conf_sum = row.pop("_confidence_sum")
        row.pop("_best")
        row["Average Model Confidence (%)"] = round(conf_sum / row["Hit Count"])
        row["Priority Score"] = round(row["Weight"] * conf_sum / 100, 2)
        rows.append(row)
    rows.sort(key=lambda r: (-r["Priority Score"], r["SCF Control ID"]))
    return rows


def all_rejected(results: list[CrosswalkResult]) -> list[str]:
    """Every rejected ID across a batch, once each, in first-seen order."""
    return list(dict.fromkeys(rid for r in results for rid in r.rejected))
