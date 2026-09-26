"""Turn AWS Security Hub (ASFF) findings into text worth mapping."""

import json
import re


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


# Security Hub control IDs look like "CloudFront.3" or "IAM.6". Requiring a
# leading letter keeps CIS rule numbers ("1.4", from GeneratorIds such as
# ".../cis-aws-foundations-benchmark/v/1.2.0/rule/1.4") from being read as one.
_CONTROL_ID = re.compile(r"^[A-Za-z][A-Za-z0-9]*\.\d+$")


def finding_control_id(finding: object) -> str | None:
    """
    The Security Hub control a finding belongs to (e.g. "CloudFront.3"), if any.

    Checked in order: Compliance.SecurityControlId (consolidated control
    findings), ProductFields.ControlId, and the last segment of GeneratorId
    (standard-specific findings, ".../v/1.0.0/CloudFront.3").
    """
    if not isinstance(finding, dict):
        return None
    candidates = [
        (finding.get("Compliance") or {}).get("SecurityControlId"),
        (finding.get("ProductFields") or {}).get("ControlId"),
        str(finding.get("GeneratorId") or "").rsplit("/", 1)[-1],
    ]
    for value in candidates:
        if isinstance(value, str) and _CONTROL_ID.match(value.strip()):
            return value.strip()
    return None
