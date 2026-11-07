"""Tests for NIST IR 8477 relationship qualifiers and dual-clause quote extraction."""

import csv
import io
import json
import pytest

from crosswalk import CrosswalkInput, CrosswalkResult, detail_rows
from exports import (
    OSCAL_VERSION,
    NIST_RELATIONSHIP_TO_OSCAL,
    oscal_mapping_collection,
    to_safe_csv,
)
from mapper import (
    MappedControl,
    MappingResult,
    _normalize_relationship,
    _validate_mapping_result,
)


def test_normalize_relationship():
    """NIST IR 8477 relationship normalizer handles exact matches, variations, and defaults."""
    assert _normalize_relationship("equal") == "equal"
    assert _normalize_relationship("subset") == "subset"
    assert _normalize_relationship("superset") == "superset"
    assert _normalize_relationship("intersects") == "intersects"
    assert _normalize_relationship("no_relationship") == "no_relationship"

    # Hyphenated / spaced variations
    assert _normalize_relationship("subset-of") == "subset"
    assert _normalize_relationship("subset_of") == "subset"
    assert _normalize_relationship("superset-of") == "superset"
    assert _normalize_relationship("no-relationship") == "no_relationship"
    assert _normalize_relationship("no relationship") == "no_relationship"
    assert _normalize_relationship("EQUAL") == "equal"

    # Unknown or non-string inputs fallback to intersects
    assert _normalize_relationship("arbitrary_string") == "intersects"
    assert _normalize_relationship(None) == "intersects"
    assert _normalize_relationship(123) == "intersects"


def test_mapped_control_defaults_and_validation():
    """MappedControl defaults relationship to intersects and coerces invalid/variant strings."""
    # Defaults
    mc_default = MappedControl(
        control_id="CRY-01",
        confidence=85,
        justification="Encryption requirement",
    )
    assert mc_default.relationship == "intersects"
    assert mc_default.source_quote == ""
    assert mc_default.control_quote == ""

    # Explicit fields & normalization
    mc_explicit = MappedControl(
        control_id="CRY-01",
        confidence=95,
        relationship="subset-of",
        source_quote="All S3 buckets must be encrypted with KMS keys",
        control_quote="Stored data is encrypted at rest using strong cryptography",
        justification="Bucket KMS encryption satisfies generic encryption at rest requirement",
    )
    assert mc_explicit.relationship == "subset"
    assert "S3 buckets" in mc_explicit.source_quote
    assert "encrypted at rest" in mc_explicit.control_quote


def test_validate_mapping_result_preserves_and_trims_quotes():
    """_validate_mapping_result normalizes relationships and strips quote whitespace."""
    raw_result = MappingResult(
        mappings=[
            MappedControl(
                control_id="CRY-01",
                confidence=90,
                relationship="  equal  ",
                source_quote="   Must use TLS 1.3   ",
                control_quote="   Enforce TLS 1.3 for all in-transit traffic   ",
                justification="Direct match",
            )
        ]
    )
    allowed = {
        "CRY-01": {
            "domain": "Cryptographic Protections",
            "description": "Enforce TLS 1.3 for all in-transit traffic",
            "regulations": {"NIST 800-53 rev5": "SC-8"},
        }
    }
    validated = _validate_mapping_result(raw_result, allowed)
    assert len(validated.mappings) == 1
    m = validated.mappings[0]
    assert m.relationship == "equal"
    assert m.source_quote == "Must use TLS 1.3"
    assert m.control_quote == "Enforce TLS 1.3 for all in-transit traffic"
    assert m.domain == "Cryptographic Protections"


def test_oscal_export_encodes_nist_ir_8477_and_quotes():
    """OSCAL mapping-collection translates NIST IR 8477 relationships and includes quotes in remarks."""
    results = [
        CrosswalkResult(
            input=CrosswalkInput(
                label="Finding 1: S3 Public Access",
                text="S3 bucket allows public read access",
                source_id="S3.1",
            ),
            mappings=[
                MappedControl(
                    control_id="DCH-01",
                    confidence=95,
                    relationship="subset",
                    source_quote="S3 bucket allows public read access",
                    control_quote="Public access to object storage is strictly prohibited",
                    justification="S3 public access finding is a subset of general public object storage controls",
                ),
                MappedControl(
                    control_id="CRY-01",
                    confidence=70,
                    relationship="superset",
                    source_quote="S3 bucket encryption and bucket policy check",
                    control_quote="Stored data is encrypted at rest",
                    justification="Finding covers access and encryption, broader than storage encryption alone",
                ),
            ],
        ),
        CrosswalkResult(
            input=CrosswalkInput(
                label="Policy: Password History",
                text="Passwords must not repeat previous 24 passwords",
                source_id=None,
            ),
            mappings=[
                MappedControl(
                    control_id="IAM-02",
                    confidence=90,
                    relationship="equal",
                    source_quote="Passwords must not repeat previous 24 passwords",
                    control_quote="Enforce password history of at least 24 remembered passwords",
                    justification="Exact match on password history requirement",
                )
            ],
        ),
    ]

    assert NIST_RELATIONSHIP_TO_OSCAL["subset"] == "subset-of"
    assert NIST_RELATIONSHIP_TO_OSCAL["superset"] == "superset-of"
    assert NIST_RELATIONSHIP_TO_OSCAL["equal"] == "equal"
    assert NIST_RELATIONSHIP_TO_OSCAL["intersects"] == "intersects-with"
    assert NIST_RELATIONSHIP_TO_OSCAL["no_relationship"] == "no-relationship"

    doc = oscal_mapping_collection(results, scf_version="SCF 2025.4")[
        "mapping-collection"
    ]
    assert doc["metadata"]["oscal-version"] == OSCAL_VERSION

    # Find the maps in the control mapping and statement mapping
    all_maps = []
    for mapping in doc["mappings"]:
        all_maps.extend(mapping["maps"])

    by_target = {m["targets"][0]["id-ref"]: m for m in all_maps}

    # Verify subset -> subset-of
    dch = by_target["DCH-01"]
    assert dch["relationship"] == "subset-of"
    assert dch["confidence-score"] == {"percentage": 0.95}
    assert 'Source clause: "S3 bucket allows public read access"' in dch["remarks"]
    assert (
        'Control clause: "Public access to object storage is strictly prohibited"'
        in dch["remarks"]
    )

    # Verify superset -> superset-of
    cry = by_target["CRY-01"]
    assert cry["relationship"] == "superset-of"
    assert 'Source clause: "S3 bucket encryption' in cry["remarks"]

    # Verify equal -> equal
    iam = by_target["IAM-02"]
    assert iam["relationship"] == "equal"
    assert (
        'Source clause: "Passwords must not repeat previous 24 passwords"'
        in iam["remarks"]
    )

    # If compliance-trestle is installed, validate schema
    trestle_mapping = pytest.importorskip(
        "trestle.oscal.mapping", reason="trestle not installed"
    )
    model = trestle_mapping.Model.model_validate_json(
        json.dumps({"mapping-collection": doc})
    )
    assert len(model.mapping_collection.mappings) == 2


def test_detail_rows_and_csv_export_contain_nist_ir_8477_columns():
    """detail_rows includes relationship, source clause, and control clause, and CSV neutralizes formula injection."""
    results = [
        CrosswalkResult(
            input=CrosswalkInput(
                label="Audit Rule 1", text="Require MFA", source_id="IAM.5"
            ),
            mappings=[
                MappedControl(
                    control_id="IAM-03",
                    confidence=92,
                    relationship="subset",
                    source_quote="=HYPERLINK('http://malicious.test')",
                    control_quote="Require MFA for administrative logins",
                    justification="Rule covers all logins whereas control specifies admin logins",
                )
            ],
        )
    ]
    rows = detail_rows(results)
    assert len(rows) == 1
    r = rows[0]
    assert r["NIST IR 8477 Relationship"] == "subset"
    assert r["Source Clause"] == "=HYPERLINK('http://malicious.test')"
    assert r["Control Clause"] == "Require MFA for administrative logins"

    # Verify safe CSV neutralizes potential formula in source clause
    import pandas as pd

    df = pd.DataFrame(rows)
    csv_bytes = to_safe_csv(df, demo=False)
    csv_text = csv_bytes.decode("utf-8")
    parsed_csv = list(csv.reader(io.StringIO(csv_text)))
    headers = parsed_csv[0]
    assert "NIST IR 8477 Relationship" in headers
    assert "Source Clause" in headers
    assert "Control Clause" in headers

    row_data = dict(zip(headers, parsed_csv[1]))
    # Formula prefix must be escaped with leading apostrophe
    assert row_data["Source Clause"] == "'=HYPERLINK('http://malicious.test')"
