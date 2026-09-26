"""Compare an existing control list with the SCF controls mapped to a framework."""

from dataclasses import dataclass, field

import pandas as pd

STATUS_COVERED = "✅ Listed"
STATUS_GAP = "❌ Not listed"


@dataclass
class GapReport:
    framework_columns: list[str]
    rows: list[dict]
    id_column: str
    # IDs in the uploaded list that are not SCF control IDs. They cannot match
    # anything, which usually means the list uses its own numbering.
    unknown_ids: list[str] = field(default_factory=list)

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


def detect_id_column(df: pd.DataFrame) -> str:
    """The first column named like "Control ID", else the first column."""
    for col in df.columns:
        name = str(col).lower()
        if "control" in name and "id" in name:
            return str(col)
    return str(df.columns[0])


def analyze_gaps(
    scf_data: list[dict],
    columns: list[str],
    existing: pd.DataFrame,
    id_column: str | None = None,
) -> GapReport:
    """
    List every SCF control that SCF maps to any of `columns`, and mark it as
    listed when its exact SCF control ID appears in the uploaded list.

    "Listed" means only that the ID is present. It does not check that the
    control is designed or operating effectively.
    """
    id_column = id_column or detect_id_column(existing)
    existing_ids = {
        str(v).strip().upper() for v in existing[id_column].dropna() if str(v).strip()
    }
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
        unknown_ids=sorted(existing_ids - scf_ids),
    )
