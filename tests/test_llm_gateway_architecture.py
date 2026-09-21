from pathlib import Path
ROOT=Path(__file__).parents[1]/"jmoraIs"
def test_only_gateway_contains_provider_adapter_or_model_api_markers():
    violations=[]
    for path in ROOT.rglob("*.py"):
        if "llm_gateway" in path.parts or path.name=="embeddings.py":continue
        source=path.read_text().casefold()
        if any(token in source for token in ("openai(","anthropic(","generativeai","/v1/responses")):violations.append(path)
    assert not violations
def test_gateway_domain_has_no_sdk_database_or_infrastructure_dependency():
    source=(ROOT/"llm_gateway"/"domain.py").read_text().casefold();assert "sqlalchemy" not in source and "import openai" not in source and "import anthropic" not in source
def test_audit_model_does_not_persist_prompt_or_payload_fields():
    source=(ROOT/"llm_gateway"/"domain.py").read_text();block=source.split("class PromptAudit:",1)[1]
    assert "prompt_text" not in block and "input_dto" not in block and "output_text" not in block

def test_correlation_enters_through_tenant_boundary_and_not_provider():
    application=(ROOT/"llm_gateway"/"application.py").read_text();providers=(ROOT/"llm_gateway"/"infrastructure.py").read_text()
    assert "current_tenant_context" in application and "LLMInvocationContext" in application
    provider_block=providers.split("class MockProviderAdapter",1)[1]
    assert "correlation_id" not in provider_block and "evaluation" not in application
    domain=(ROOT/"llm_gateway"/"domain.py").read_text()
    assert "request_id:str" in domain and "correlation_id:str" in domain

def test_invocation_persists_canonical_classification_and_trusted_request_configuration_only():
    domain=(ROOT/"llm_gateway"/"domain.py").read_text();application=(ROOT/"llm_gateway"/"application.py").read_text()
    invocation=domain.split("class LLMInvocation:",1)[1].split("class PromptAudit:",1)[0]
    assert "LLMOutputClassification" in invocation and "temperature" in invocation and "seed" in invocation
    assert "r.temperature" in application and "r.seed" in application and "classification,r.temperature,r.seed" in application
    for forbidden in ("output_text", "input_dto", "system_prompt", "canonical_payload"):
        assert forbidden not in invocation

def test_invocation_context_persistence_is_operational_only_and_provider_independent():
    domain=(ROOT/"llm_gateway"/"domain.py").read_text();ports=(ROOT/"llm_gateway"/"ports.py").read_text();persistence=(ROOT/"llm_gateway"/"persistence.py").read_text();providers=(ROOT/"llm_gateway"/"infrastructure.py").read_text()
    context=domain.split("class LLMInvocationContext:",1)[1].split("@dataclass",1)[0]
    assert "LLMInvocationContextRepository" in ports and "LLMInvocationContextQueryPort" in ports
    assert "PostgreSQLLLMInvocationContextRepository" in persistence
    for forbidden in ("patient_id","patient_name","cpf","email","phone","clinical_text","raw_prompt","raw_response","jwt","password","api_key"):
        assert forbidden not in context.casefold()
    provider_block=providers.split("class MockProviderAdapter",1)[1]
    assert "LLMInvocationContext(" not in provider_block and "evaluation" not in persistence

def test_persisted_input_keeps_owner_repositories_outside_gateway_and_payload_outside_persistence():
    application=(ROOT/"llm_gateway"/"application.py").read_text();persistence=(ROOT/"llm_gateway"/"persistence.py").read_text();domain=(ROOT/"llm_gateway"/"domain.py").read_text()
    for forbidden in ("MedicalDocumentRepository","AuditDefenseRepository","OrthopedicAssessmentRepository","ClinicalReasoningInputRepository","evaluation.e2e_acceptance"):
        assert forbidden not in application and forbidden not in persistence and forbidden not in domain
    invocation=domain.split("class LLMInvocation:",1)[1].split("class PromptAudit:",1)[0]
    assert "UpstreamArtifactReference" in invocation
    for forbidden in ("input_dto","canonical_payload","document.sections","output_text"):
        assert forbidden not in invocation
    for owner in ("medical_documents","audit_defense","orthopedic_intelligence","reasoning_input"):
        assert (ROOT/owner/"gateway_input.py").exists()
