import csv
import io
import json

import pandas as pd
import pytest

from crosswalk import CrosswalkInput, CrosswalkResult
from exports import OSCAL_VERSION, oscal_mapping_collection, to_safe_csv
from mapper import MappedControl


def _result(label, source_id, *pairs):
    return CrosswalkResult(
        input=CrosswalkInput(label, label, source_id),
        mappings=[
            MappedControl(control_id=cid, confidence=conf, justification=f"why {cid}")
            for cid, conf in pairs
        ],
    )


def test_csv_neutralizes_formulas():
    df = pd.DataFrame(
        {
            "a": ['=HYPERLINK("http://x")', "+1", "-2", "@SUM(A1)", "safe", "\tTAB"],
            "n": [1, 2, 3, 4, 5, 6],
        }
    )
    rows = list(csv.reader(io.StringIO(to_safe_csv(df).decode("utf-8"))))
    assert [r[0] for r in rows[1:]] == [
        '\'=HYPERLINK("http://x")',
        "'+1",
        "'-2",
        "'@SUM(A1)",
        "safe",
        "'\tTAB",
    ]
    assert [r[1] for r in rows[1:]] == ["1", "2", "3", "4", "5", "6"]


def test_oscal_groups_sources_and_merges_duplicates():
    results = [
        _result("Finding 1", "CloudFront.3", ("CRY-03", 70)),
        _result("Finding 2", "CloudFront.3", ("CRY-03", 90), ("NET-01", 40)),
        _result("policy.txt", None, ("CRY-01", 80)),
    ]
    doc = oscal_mapping_collection(
        results, scf_version="SCF 2025.4", last_modified="2026-09-26T00:00:00+00:00"
    )["mapping-collection"]

    assert doc["metadata"]["oscal-version"] == OSCAL_VERSION
    assert doc["metadata"]["remarks"] == "SCF release: SCF 2025.4"
    assert doc["provenance"]["status"] == "draft"
    assert doc["provenance"]["method"] == "automation"

    control_mapping, statement_mapping = doc["mappings"]
    assert control_mapping["source-resource"]["type"] == "aws-security-hub-controls"
    pairs = {
        (m["sources"][0]["id-ref"], m["targets"][0]["id-ref"]): m
        for m in control_mapping["maps"]
    }
    assert set(pairs) == {("CloudFront.3", "CRY-03"), ("CloudFront.3", "NET-01")}
    merged = pairs[("CloudFront.3", "CRY-03")]
    assert merged["confidence-score"] == {"percentage": 0.9}
    assert merged["relationship"] == "intersects-with"
    assert merged["remarks"] == "Finding 2: why CRY-03"

    [statement_map] = statement_mapping["maps"]
    assert statement_map["sources"] == [{"type": "statement", "id-ref": "input-3"}]
    assert statement_mapping["target-resource"]["type"] == "control-framework"

    # Every #uuid reference resolves to a back-matter resource.
    resources = {r["uuid"]: r for r in doc["back-matter"]["resources"]}
    for mapping in doc["mappings"]:
        for side in ("source-resource", "target-resource"):
            href = mapping[side]["href"]
            assert href.startswith("#") and href[1:] in resources
    scf = resources[control_mapping["target-resource"]["href"][1:]]
    assert scf["title"] == "Secure Controls Framework (SCF), SCF 2025.4"
    assert scf["rlinks"][0]["href"].startswith(
        "https://github.com/securecontrolsframework/"
    )
    inputs = resources[statement_mapping["source-resource"]["href"][1:]]
    assert "input-3: policy.txt" in inputs["description"]


def test_oscal_output_validates_against_trestle_models():
    """The export parses as an OSCAL mapping-collection (compliance-trestle's models)."""
    mapping = pytest.importorskip("trestle.oscal.mapping")
    results = [
        _result("Finding 1", "CloudFront.3", ("CRY-03", 90)),
        _result("policy.txt", None, ("CRY-01", 80), ("IAC-06", 55)),
    ]
    doc = oscal_mapping_collection(results)
    model = mapping.Model.model_validate_json(json.dumps(doc))
    collection = model.mapping_collection
    assert len(collection.mappings) == 2
    assert collection.provenance.status == "draft"
