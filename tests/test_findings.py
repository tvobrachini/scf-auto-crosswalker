import json
import os

from findings import finding_to_text, is_securityhub_export

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


def test_finding_control_id_sources():
    from findings import finding_control_id

    assert finding_control_id({"Compliance": {"SecurityControlId": "S3.8"}}) == "S3.8"
    assert finding_control_id({"ProductFields": {"ControlId": "IAM.6"}}) == "IAM.6"
    assert (
        finding_control_id(
            {
                "GeneratorId": "aws-foundational-security-best-practices/v/1.0.0/CloudFront.3"
            }
        )
        == "CloudFront.3"
    )
    assert finding_control_id({"GeneratorId": "arn:aws:guardduty:custom"}) is None
    assert finding_control_id({"Compliance": None}) is None
    assert finding_control_id("not a finding") is None


def test_lab_finding_title_matches_its_control():
    from findings import finding_control_id

    with open(LAB_FINDING, encoding="utf-8") as f:
        finding = json.load(f)["Findings"][0]
    assert finding_control_id(finding) == "CloudFront.3"
    assert finding["Title"].startswith("CloudFront.3 ")


def test_cis_and_pci_generator_ids_are_not_control_ids():
    from findings import finding_control_id

    cis = "arn:aws:securityhub:::ruleset/cis-aws-foundations-benchmark/v/1.2.0/rule/1.4"
    assert finding_control_id({"GeneratorId": cis}) is None
    assert (
        finding_control_id(
            {"GeneratorId": "cis-aws-foundations-benchmark/v/1.4.0/1.10"}
        )
        is None
    )
    assert finding_control_id({"GeneratorId": "pci-dss/v/3.2.1/PCI.IAM.1"}) is None
    assert (
        finding_control_id({"GeneratorId": "security-control/Lambda.1"}) == "Lambda.1"
    )
