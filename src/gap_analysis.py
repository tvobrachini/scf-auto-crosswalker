"""Compare an existing control list with the SCF controls mapped to a framework."""

import re
from dataclasses import dataclass, field

import pandas as pd

STATUS_COVERED = "✅ Listed"
STATUS_GAP = "❌ Not listed"

# Status values counted as "in place" by default when the user picks a
# status column: anything mentioning implemented/in place/active/yes, unless
# it is negated ("not implemented") or partial/planned.
_POSITIVE = re.compile(r"\b(implemented|in place|active|operating|effective|yes)\b")
_NEGATIVE = re.compile(r"\b(not|no|partial(ly)?|planned|pending|in progress)\b")


@dataclass
class GapReport:
    framework_columns: list[str]
    rows: list[dict]
    id_column: str
    # IDs in the uploaded list that are not SCF control IDs. They cannot match
    # anything, which usually means the list uses its own numbering.
    unknown_ids: list[str] = field(default_factory=list)
    # SCF IDs present in the list but excluded by the status filter.
    excluded_by_status: list[str] = field(default_factory=list)

    @property
    def covered(self) -> int:
        return sum(1 for r in self.rows if r["Status"] == STATUS_COVERED)

    @property
    def gaps(self) -> int:
        return len(self.rows) - self.covered


def framework_columns(scf_data: list[dict], framework: str) -> list[str]:
    """
    SCF crosswalk columns whose name contains the framework name.

    Spaces and case are ignored, so "SOC 2" finds "AICPA SOC 2 (2017)". One
    framework can have several columns (e.g. two ISO 27001 editions); callers
    should let the user pick one.
    """
    needle = framework.lower().replace(" ", "")
    found = {
        col
        for control in scf_data
        for col in (control.get("regulations") or {})
        if needle in col.lower().replace(" ", "")
    }
    return sorted(found)


def _words(name: object) -> list[str]:
    return re.findall(r"[a-z0-9]+", str(name).lower())


def detect_id_column(df: pd.DataFrame) -> str:
    """
    The column most likely to hold control IDs.

    Prefers a column whose words are exactly "control id", "scf id" or
    "scf control id", then any column containing the words "control" and "id"
    (whole words, so "Control Provider" does not count), else the first column.
    """
    exact = {("control", "id"), ("scf", "id"), ("scf", "control", "id"), ("id",)}
    for col in df.columns:
        if tuple(_words(col)) in exact:
            return str(col)
    for col in df.columns:
        words = set(_words(col))
        if {"control", "id"} <= words:
            return str(col)
    return str(df.columns[0])


def detect_status_column(df: pd.DataFrame) -> str | None:
    """A column named like "Status" or "Implementation Status", if any."""
    for col in df.columns:
        if "status" in _words(col):
            return str(col)
    return None


def default_in_place_statuses(values: list[str]) -> list[str]:
    """The subset of status values that read as "in place"."""
    return [
        v
        for v in values
        if _POSITIVE.search(v.lower()) and not _NEGATIVE.search(v.lower())
    ]


def analyze_gaps(
    scf_data: list[dict],
    columns: list[str],
    existing: pd.DataFrame,
    id_column: str | None = None,
    status_column: str | None = None,
    in_place_statuses: list[str] | None = None,
) -> GapReport:
    """
    List every SCF control that SCF maps to any of `columns`, and mark it as
    listed when its exact SCF control ID appears in the uploaded list.

    With `status_column`, only rows whose status is in `in_place_statuses`
    count. "Listed" still means only that the ID is present with such a
    status; it does not check that the control is designed or operating
    effectively.
    """
    id_column = id_column or detect_id_column(existing)

    def ids(frame: pd.DataFrame) -> set[str]:
        return {
            str(v).strip().upper() for v in frame[id_column].dropna() if str(v).strip()
        }

    all_ids = ids(existing)
    counted = existing
    if status_column is not None:
        allowed = {s.strip().lower() for s in (in_place_statuses or [])}
        status = existing[status_column].astype(str).str.strip().str.lower()
        counted = existing[status.isin(allowed)]
    existing_ids = ids(counted)

    scf_ids = {c["control_id"].upper() for c in scf_data}

    rows = []
    for control in scf_data:
        regs = control.get("regulations") or {}
        refs = {col: regs[col] for col in columns if col in regs}
        if not refs:
            continue
        cid = control["control_id"]
        rows.append(
            {
                "Status": STATUS_COVERED if cid.upper() in existing_ids else STATUS_GAP,
                "SCF Control ID": cid,
                "Domain": control.get("domain", ""),
                "Description": control.get("description", ""),
                "Framework References": "; ".join(
                    f"{col}: {ref}" for col, ref in refs.items()
                ),
                "Evidence Request List (ERL)": control.get("erl", ""),
                "Control Question": control.get("question", ""),
            }
        )

    return GapReport(
        framework_columns=list(columns),
        rows=rows,
        id_column=str(id_column),
        unknown_ids=sorted(all_ids - scf_ids),
        excluded_by_status=sorted((all_ids & scf_ids) - existing_ids),
    )
