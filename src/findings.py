"""Turn AWS Security Hub (ASFF) findings into text worth mapping."""

import json


def is_securityhub_export(data: object) -> bool:
    """True for a Security Hub export: a JSON object with a "Findings" list."""
    return (
        isinstance(data, dict)
        and "Findings" in data
        and isinstance(data["Findings"], list)
    )


def finding_to_text(finding: dict) -> str:
    """
    Keep the parts of an ASFF finding that describe the control problem.

    A raw finding starts with several hundred characters of ARNs, IDs and
    timestamps. The embedding model reads only the first 256 word pieces, and
    those fields say nothing about which control failed, so the title,
    description, remediation text, resource types and compliance status are
    extracted instead. Anything that is not a recognizable finding is
    returned as JSON unchanged.
    """
    if not isinstance(finding, dict) or not (
        finding.get("Title") or finding.get("Description")
    ):
        return json.dumps(finding, indent=2)

    lines = []
    if finding.get("Title"):
        lines.append(f"Title: {finding['Title']}")
    if finding.get("Description"):
        lines.append(f"Description: {finding['Description']}")

    remediation = (finding.get("Remediation") or {}).get("Recommendation") or {}
    if remediation.get("Text"):
        lines.append(f"Remediation: {remediation['Text']}")

    resource_types = sorted(
        {
            r["Type"]
            for r in finding.get("Resources") or []
            if isinstance(r, dict) and r.get("Type")
        }
    )
    if resource_types:
        lines.append(f"Resource types: {', '.join(resource_types)}")

    severity = (finding.get("Severity") or {}).get("Label")
    if severity:
        lines.append(f"Severity: {severity}")

    status = (finding.get("Compliance") or {}).get("Status")
    if status:
        lines.append(f"Compliance status: {status}")

    return "\n".join(lines)
