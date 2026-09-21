from pathlib import Path
ROOT=Path(__file__).parents[1]/"jmoraIs"/"orthopedic_intelligence"
def test_orthopedic_domain_has_no_infrastructure_or_connector_dependencies():
    source=(ROOT/"domain.py").read_text()
    assert "sqlalchemy" not in source and "jmoraIs.connect" not in source and "patient_context" not in source
def test_application_has_no_raw_scientific_or_patient_access():
    source=(ROOT/"application.py").read_text()
    for forbidden in ("jmoraIs.connect","PubMed","PatientContext","EvidencePackage"):
        assert forbidden not in source
def test_boundary_is_clinical_reasoning_input_only_and_domain_is_frozen():
    assert "isinstance(value,ClinicalReasoningInput)" in (ROOT/"application.py").read_text()
    assert "@dataclass(frozen=True)" in (ROOT/"domain.py").read_text()
def test_projection_respects_application_infrastructure_boundary():
    projection=(ROOT/"projection.py").read_text();persistence=(ROOT/"projection_persistence.py").read_text()
    clinical_state=(ROOT.parent/"clinical_state/domain.py").read_text()
    assert "sqlalchemy" not in projection.lower()
    assert "PostgreSQLGovernedOrthopedicStateQueryAdapter" in persistence
    assert "orthopedic_intelligence" not in clinical_state
    assert "e2e_acceptance" not in projection+persistence
