import json
import os

from src.findings import finding_to_text, is_securityhub_export

LAB_FINDING = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "lab_data",
    "aws_securityhub_finding.json",
)


def test_is_securityhub_export():
    assert is_securityhub_export({"Findings": []})
    assert not is_securityhub_export({"Findings": "x"})
    assert not is_securityhub_export([{"Title": "x"}])


def test_finding_to_text_keeps_control_relevant_fields():
    with open(LAB_FINDING, encoding="utf-8") as f:
        finding = json.load(f)["Findings"][0]
    text = finding_to_text(finding)
    assert text.startswith("Title: ")
    assert "Description: " in text
    assert "Remediation: " in text
    assert "Resource types: AwsCloudFrontDistribution" in text
    assert "Compliance status: FAILED" in text
    # Identifiers that carry no control meaning are left out.
    assert "arn:aws" not in text
    assert "123456789012" not in text


def test_finding_to_text_falls_back_to_json():
    data = {"foo": "bar"}
    assert json.loads(finding_to_text(data)) == data


def test_finding_to_text_tolerates_missing_sections():
    text = finding_to_text({"Title": "T", "Remediation": None, "Resources": [None]})
    assert text == "Title: T"
