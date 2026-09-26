"""CSV and OSCAL exports of crosswalk results."""

import uuid
from datetime import datetime, timezone

import pandas as pd

from crosswalk import CrosswalkResult

# Spreadsheet apps treat a cell starting with one of these as a formula.
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _neutralize(value: object) -> object:
    if isinstance(value, str) and value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


def to_safe_csv(df: pd.DataFrame) -> bytes:
    """
    CSV bytes with formula injection neutralized.

    Model output and uploaded data are untrusted; a cell such as
    '=HYPERLINK(...)' would run as a formula when the CSV is opened in a
    spreadsheet. Such cells are prefixed with an apostrophe.
    """
    safe = df.copy()
    for col in safe.columns:
        if safe[col].dtype == object:
            safe[col] = safe[col].map(_neutralize)
    return safe.to_csv(index=False).encode("utf-8")


# --- OSCAL ----------------------------------------------------------------------

OSCAL_VERSION = "1.2.1"
SCF_HREF = "https://github.com/securecontrolsframework/securecontrolsframework/releases"
SECURITY_HUB_HREF = "https://docs.aws.amazon.com/securityhub/latest/userguide/securityhub-controls-reference.html"

MAPPING_DESCRIPTION = (
    "Unreviewed suggestions from SCF Auto-Crosswalker: embedding retrieval over the "
    "SCF, one language-model call, and validation that each target is one of the "
    "retrieved SCF controls. The relationship is recorded as intersects-with, the "
    "weakest positive relationship in NIST IR 8477, because the tool does not "
    "determine subset, superset or equality. Confidence scores are the model's own "
    "and are not calibrated. A person must review every map before relying on it."
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def oscal_mapping_collection(
    results: list[CrosswalkResult],
    title: str = "SCF Auto-Crosswalker suggestions",
    scf_version: str | None = None,
    last_modified: str | None = None,
) -> dict:
    """
    Build an OSCAL mapping-collection (OSCAL 1.2 mapping model) from crosswalk
    results, as a JSON-ready dict. Callers should only export results that
    have at least one mapping.

    Inputs with a Security Hub control ID become `control` sources in a
    mapping whose source resource is the Security Hub controls reference.
    Other inputs (policy text, documents) become `statement` sources in a
    second mapping. Targets are SCF controls. Duplicate (source, target)
    pairs are merged, keeping the highest confidence.
    """
    groups: dict[str, dict[tuple[str, str], dict]] = {"control": {}, "statement": {}}
    for index, r in enumerate(results, start=1):
        if r.input.source_id:
            kind, source_ref = "control", r.input.source_id
        else:
            kind, source_ref = "statement", f"input-{index}"
        for m in r.mappings:
            key = (source_ref, m.control_id)
            current = groups[kind].get(key)
            if current is None or m.confidence > current["confidence"]:
                groups[kind][key] = {
                    "confidence": m.confidence,
                    "justification": m.justification,
                    "label": r.input.label,
                }

    # Neither the SCF nor the Security Hub controls reference is published as
    # an OSCAL catalog, so the source and target resources are typed with
    # their own tokens and point, by UUID, to back-matter resources that link
    # to where each is published.
    scf_resource = {
        "uuid": str(uuid.uuid4()),
        "title": "Secure Controls Framework (SCF)"
        + (f", {scf_version}" if scf_version else ""),
        "description": "SCF control catalog workbook, as published on GitHub.",
        "rlinks": [{"href": SCF_HREF}],
    }
    hub_resource = {
        "uuid": str(uuid.uuid4()),
        "title": "AWS Security Hub controls reference",
        "rlinks": [{"href": SECURITY_HUB_HREF}],
    }
    statement_labels = [
        f"input-{index}: {r.input.label}"
        for index, r in enumerate(results, start=1)
        if not r.input.source_id and r.mappings
    ]
    inputs_resource = {
        "uuid": str(uuid.uuid4()),
        "title": "Crosswalk inputs",
        "description": "Text inputs mapped by SCF Auto-Crosswalker, by statement ID: "
        + "; ".join(statement_labels),
    }

    resources = {
        "control": ("aws-security-hub-controls", hub_resource),
        "statement": ("input-document", inputs_resource),
    }
    used = [scf_resource]

    mappings = []
    for kind, pairs in groups.items():
        if not pairs:
            continue
        maps = []
        for (source_ref, target_id), info in pairs.items():
            maps.append(
                {
                    "uuid": str(uuid.uuid4()),
                    "relationship": "intersects-with",
                    "sources": [{"type": kind, "id-ref": source_ref}],
                    "targets": [{"type": "control", "id-ref": target_id}],
                    "confidence-score": {"percentage": info["confidence"] / 100},
                    "remarks": f"{info['label']}: {info['justification']}",
                }
            )
        source_type, source_resource = resources[kind]
        used.append(source_resource)
        mappings.append(
            {
                "uuid": str(uuid.uuid4()),
                "source-resource": {
                    "type": source_type,
                    "href": f"#{source_resource['uuid']}",
                },
                "target-resource": {
                    "type": "control-framework",
                    "href": f"#{scf_resource['uuid']}",
                },
                "maps": maps,
            }
        )

    remarks = "SCF release: " + (scf_version or "not recorded")
    return {
        "mapping-collection": {
            "uuid": str(uuid.uuid4()),
            "metadata": {
                "title": title,
                "last-modified": last_modified or _now(),
                "version": "1.0",
                "oscal-version": OSCAL_VERSION,
                "remarks": remarks,
            },
            "provenance": {
                "method": "automation",
                "matching-rationale": "semantic",
                "status": "draft",
                "mapping-description": MAPPING_DESCRIPTION,
            },
            "mappings": mappings,
            "back-matter": {"resources": used},
        }
    }
