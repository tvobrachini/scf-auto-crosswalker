import pytest
from unittest.mock import patch
from src.mapper import construct_scf_context, MappedControl, ScopeRecommendation

# --- Dummy Data ---
DUMMY_SCF_DATA = [
    {
        "control_id": "GOV-01",
        "domain": "Governance",
        "description": "Establish an Information Security Program.",
        "regulations": {"SOC 2": "CC1.1", "ISO 27001": "A.5.1"}
    },
    {
        "control_id": "CRY-01",
        "domain": "Cryptography",
        "description": "All sensitive data must be encrypted at rest utilizing AES-256.",
        "regulations": {"PCI DSS": "Req 3", "GDPR": "Art. 32"}
    }
]

# --- Tests ---

def test_construct_scf_context():
    """Test that the SCF context builder properly formats the raw JSON data for the LLM."""
    context = construct_scf_context(DUMMY_SCF_DATA)
    # Check if format [ID] Domain: Description is followed
    assert "[GOV-01] Governance: Establish an Information Security Program." in context
    assert "[CRY-01] Cryptography: All sensitive data must be encrypted at rest utilizing AES-256." in context
    
def test_mapped_control_model():
    """Test the Pydantic data model validation for mappings."""
    control = MappedControl(
        control_id="CRY-01",
        domain="Cryptography",
        confidence=95,
        justification="The input mentions AES encryption.",
        regulations={"PCI": "1.2"}
    )
    assert control.confidence == 95
    assert control.control_id == "CRY-01"

def test_scope_recommendation_model():
    """Test the Pydantic data model validation for audit scope recommendations."""
    scope = ScopeRecommendation(
        recommended_domains=["Governance", "Risk"],
        recommended_control_ids=["GOV-01", "RSK-02"],
        reasoning="The scope covers overall governance."
    )
    assert len(scope.recommended_domains) == 2
    assert "GOV-01" in scope.recommended_control_ids

@patch('src.mapper.load_scf_database')
def test_mapper_handles_empty_db(mock_load):
    """Test that the mapper gracefully handles a missing SCF database."""
    mock_load.return_value = []
    
    from src.mapper import map_text_to_scf, analyze_audit_scope
    assert map_text_to_scf("Test policy") is None
    assert analyze_audit_scope("Test scope") is None
