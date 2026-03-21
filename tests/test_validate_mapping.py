from src.mapper import MappedControl, MappingResult, _validate_mapping_result


def _make_control(control_id, confidence=80):
    return MappedControl(
        control_id=control_id,
        domain="Test Domain",
        confidence=confidence,
        justification="Test justification.",
    )


def test_validate_removes_hallucinated_ids():
    """Control IDs not in the SCF database must be filtered out."""
    result = MappingResult(mappings=[_make_control("CRY-01"), _make_control("FAKE-99")])
    scf_dict = {"CRY-01": {"control_id": "CRY-01"}}
    validated = _validate_mapping_result(result, scf_dict)
    assert len(validated.mappings) == 1
    assert validated.mappings[0].control_id == "CRY-01"


def test_validate_keeps_all_valid_ids():
    result = MappingResult(mappings=[_make_control("CRY-01"), _make_control("GOV-01")])
    scf_dict = {"CRY-01": {}, "GOV-01": {}}
    validated = _validate_mapping_result(result, scf_dict)
    assert len(validated.mappings) == 2


def test_validate_clamps_confidence_above_100():
    result = MappingResult(mappings=[_make_control("GOV-01", confidence=150)])
    validated = _validate_mapping_result(result, {"GOV-01": {}})
    assert validated.mappings[0].confidence == 100


def test_validate_clamps_confidence_below_0():
    result = MappingResult(mappings=[_make_control("GOV-01", confidence=-10)])
    validated = _validate_mapping_result(result, {"GOV-01": {}})
    assert validated.mappings[0].confidence == 0


def test_validate_empty_mappings():
    result = MappingResult(mappings=[])
    validated = _validate_mapping_result(result, {"GOV-01": {}})
    assert validated.mappings == []


def test_validate_all_hallucinated():
    result = MappingResult(
        mappings=[_make_control("FAKE-01"), _make_control("FAKE-02")]
    )
    validated = _validate_mapping_result(result, {"GOV-01": {}})
    assert validated.mappings == []
