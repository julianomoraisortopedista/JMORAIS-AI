from pathlib import Path
ROOT=Path(__file__).parents[1]/"jmoraIs"/"audit_defense"
def test_domain_is_immutable_and_infrastructure_free():
    source=(ROOT/"domain.py").read_text();assert "@dataclass(frozen=True)" in source and "sqlalchemy" not in source and "jmoraIs.connect" not in source
def test_application_has_no_raw_connectors_llm_rag_payer_or_document_dependency():
    source=(ROOT/"application.py").read_text()
    for forbidden in ("jmoraIs.patient_context","EvidencePackage","PubMed","Crossref","OpenAlex","jmoraIs.connect","langchain","embedding","payer","medical_documents"):
        assert forbidden not in source
def test_canonical_input_boundary_and_no_free_text_command():
    source=(ROOT/"application.py").read_text();assert "isinstance(value,ClinicalReasoningInput)" in source and "audit_text" not in source

def test_restart_projection_is_outside_clinical_state_and_uses_existing_port():
    application=(ROOT/"application.py").read_text();ports=(ROOT/"ports.py").read_text()
    projection=(ROOT/"clinical_state_projection.py").read_text();persistence=(ROOT/"clinical_state_persistence.py").read_text()
    clinical_root=Path(__file__).parents[1]/"jmoraIs"/"clinical_state"
    assert "GovernedAuditClinicalStatePort" in ports
    assert "PostgreSQLGovernedAuditClinicalStateAdapter" in persistence
    assert "patient_clinical_state_versions" in persistence and "tenant_id" not in persistence
    assert "InMemoryAuditClinicalStateAdapter" not in persistence
    assert "evaluation" not in projection+persistence+application
    assert "payer" not in projection.lower()+persistence.lower()+application.lower()
    assert all("audit_defense" not in path.read_text() for path in clinical_root.glob("*.py"))

def test_evidence_projection_uses_canonical_services_without_duplicate_scientific_truth():
    ports=(ROOT/"ports.py").read_text();projection=(ROOT/"evidence_projection.py").read_text()
    assert "GovernedAuditEvidencePort" in ports
    assert "GovernedEvidence" in projection and "clinical_appraisal_integrity_hash" in projection
    assert "SupportDirection" not in projection
    for forbidden in ("PubMed","Crossref","OpenAlex","jmoraIs.connect","EvidencePackage(","evaluation"):
        assert forbidden not in projection
    assert "InMemory" not in projection

def test_guideline_projection_reuses_canonical_types_rules_and_persistent_ports():
    ports=(ROOT/"ports.py").read_text();projection=(ROOT/"guideline_projection.py").read_text()
    assert "GovernedAuditGuidelinePort" in ports
    assert "GuidelineRecommendationSet" in projection and "guideline_validity_issue" in projection
    for duplicate in ("class RecommendationStrength","class ConflictSeverity","class RecommendationIntent"):
        assert duplicate not in projection
    for forbidden in ("requests","httpx","PubMed","Crossref","OpenAlex","evaluation","InMemory"):
        assert forbidden not in projection

def test_terminology_projection_reconstructs_governance_without_mapping_or_provider_access():
    ports=(ROOT/"ports.py").read_text();projection=(ROOT/"terminology_projection.py").read_text()
    assert "GovernedAuditTerminologyPort" in ports
    assert "mapping_governance_integrity_hash" in projection and "get_governed" in projection
    for forbidden in ("resolve_concepts","normalize_terminology","PubMed","Crossref","requests","httpx","evaluation","InMemory"):
        assert forbidden not in projection

def test_stage12_real_service_composition_has_no_noncanonical_support_adapters():
    source=(Path(__file__).parent/"test_stage12_real_service_postgresql.py").read_text()
    for forbidden in ("InMemoryAuditClinicalStateAdapter", "InMemoryGovernedEvidenceRepository",
                      "InMemoryGuideline", "InMemoryTerminologyRepository", "jmoraIs.connect",
                      "EvidencePackage(", "evaluation.e2e_acceptance", "LLM", "RAG"):
        assert forbidden not in source
    assert "AuditDefenseService(" in source and "PostgreSQLAuditDefenseRepository" in source
