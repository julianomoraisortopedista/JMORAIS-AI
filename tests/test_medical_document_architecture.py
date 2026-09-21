from pathlib import Path
ROOT=Path(__file__).parents[1]/"jmoraIs"/"medical_documents"
def test_domain_is_immutable_and_has_no_infrastructure_leakage():
    source=(ROOT/"domain.py").read_text();assert "@dataclass(frozen=True)" in source and "sqlalchemy" not in source and "jmoraIs.connect" not in source
def test_application_has_no_raw_patient_scientific_connector_llm_or_rag_access():
    source=(ROOT/"application.py").read_text()
    for forbidden in ("jmoraIs.patient_context","EvidencePackage","PubMed","Crossref","OpenAlex","jmoraIs.connect","langchain","embedding"):
        assert forbidden not in source
def test_boundary_accepts_only_clinical_reasoning_input():
    assert "isinstance(value,ClinicalReasoningInput)" in (ROOT/"application.py").read_text()
def test_document_engine_does_not_build_vancouver_citations():
    source=(ROOT/"application.py").read_text();assert "StrictVancouverFormatter" not in source and "canonical_vancouver" in source
def test_clinical_fact_projection_respects_boundaries():
    projection=(ROOT/"clinical_state_projection.py").read_text();persistence=(ROOT/"clinical_state_persistence.py").read_text()
    clinical_state=(ROOT.parent/"clinical_state/domain.py").read_text()
    assert "sqlalchemy" not in projection.lower()
    assert "PostgreSQLGovernedDocumentClinicalStateAdapter" in persistence
    assert "medical_documents" not in clinical_state and "e2e_acceptance" not in projection+persistence
    assert "GovernedDocumentClinicalStatePort" in (ROOT/"ports.py").read_text()
def test_document_terminology_projection_uses_canonical_port_without_duplication():
    projection=(ROOT/"terminology_projection.py").read_text();persistence=(ROOT/"terminology_persistence.py").read_text()
    assert "sqlalchemy" not in projection.lower() and "ClinicalConcept" in projection
    assert "PostgreSQLGovernedDocumentTerminologyAdapter" in persistence
    assert "GovernedDocumentTerminologyPort" in (ROOT/"ports.py").read_text()
    assert "CREATE TABLE" not in persistence.upper() and "e2e_acceptance" not in projection+persistence
def test_stage11_restart_composition_uses_only_canonical_persisted_input_adapters():
    composition=(ROOT.parents[1]/"tests/test_stage11_real_service_postgresql.py").read_text()
    for required in ("PostgreSQLGovernedDocumentClinicalStateAdapter","PostgreSQLGovernedDocumentTerminologyAdapter",
      "CanonicalDocumentCitationAdapter","PostgreSQLClinicalReasoningInputRepository","SQLAlchemyGovernedEvidenceRepository",
      "PostgreSQLRecommendationRepository","PostgreSQLOrthopedicAssessmentRepository","PostgreSQLMedicalDocumentRepository"):
        assert required in composition
    for forbidden in ("InMemoryFactQueryAdapter","InMemoryReferenceQueryAdapter","jmoraIs.connect"):
        assert forbidden not in composition
    production="".join(path.read_text() for path in ROOT.glob("*.py"))
    assert "evaluation.e2e_acceptance" not in production
