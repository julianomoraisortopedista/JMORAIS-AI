from dataclasses import FrozenInstanceError,replace
from datetime import datetime,timezone
import pytest
from jmoraIs.llm_gateway import *
from tests.test_guideline_engine import ready_input
from tests.test_orthopedic_intelligence import engine as ortho_setup,view,finding
from tests.test_medical_document_engine import setup as document_setup
from tests.test_audit_defense import setup as defense_setup
from jmoraIs.tenancy.context import TenantContextBinder
from jmoraIs.tenancy.domain import TenantContext
NOW=datetime(2026,8,10,tzinfo=timezone.utc)
@pytest.fixture(autouse=True)
def trusted_invocation_context():
    with TenantContextBinder().bind_tenant(TenantContext("tenant-test","org-test","llm-test-service","INTERNAL_SERVICE","CLINICAL_VALIDATION","MIP-10.1","corr-llm-test-0001")):
        yield
def template(input_types=("CanonicalStructuredDTO",)):
    return PromptTemplate("prompt-template-1","governed summarization","Produce a draft for human review","Return only the governed structured draft.",input_types,"draft-v1","MIP-10.1")
def dto(fields=None):return CanonicalStructuredDTO("test-dto","1",tuple(fields or (StructuredField("clinical_reference","state-1","prov-1"),)),"MIP-10.1",("prov-1",))
def model(provider=LLMProvider.MOCK):return LLMModel(provider,"test-model","2026-01",1.0,2.0,True,"MIP-10.1")
def response(**changes):
    values=dict(provider_request_id="provider-1",output_text="Governed draft output",input_tokens=1000,output_tokens=500,cached_tokens=100,latency_ms=25,provider_metadata_hash="meta-hash",refused=False);values.update(changes);return ProviderResponse(**values)
def setup(responses=None,provider=None,prompt_template=None,max_retries=2):
    prompts=InMemoryPromptRepository();audit=InMemoryPromptAuditRepository();invocations=InMemoryInvocationRepository();contexts=InMemoryLLMInvocationContextRepository();governance=PromptGovernanceService(prompts,audit,clock=lambda:NOW);version=governance.register(prompt_template or template(),created_by="architect");adapter=provider or MockProviderAdapter(responses or (response(),));gateway=CanonicalLLMGateway(prompts,audit,invocations,contexts,(adapter,),clock=lambda:NOW,max_retries=max_retries)
    return gateway,prompts,audit,invocations,version,adapter
def request(version,input_dto=None,provider=LLMProvider.MOCK,**changes):
    values=dict(request_id="request-1",prompt_version_id=version.prompt_version_id,model=model(provider),input_dto=dto() if input_dto is None else input_dto,review_policy=ReviewPolicy("human-review","MIP-10.1",True,False),temperature=.2,seed=7,max_output_tokens=500,policy_version="MIP-10.1",requested_at=NOW);values.update(changes);return LLMRequest(**values)
def test_mock_provider_gateway_cost_tokens_audit_and_no_external_actionability():
    gateway,_,audit,invocations,version,adapter=setup();result=gateway.invoke(request(version))
    assert result.classification is LLMOutputClassification.APPROVED_FOR_REVIEW and not result.externally_actionable
    assert result.token_usage==TokenUsage(1000,500,100,1500) and result.cost.total_cost==.002
    assert audit.history("request-1")[0].request_hash and audit.history("request-1")[0].response_hash
    assert invocations.history("request-1")[0].latency_ms==25 and adapter.requests
    assert invocations.history("request-1")[0].correlation_id==audit.history("request-1")[0].correlation_id=="corr-llm-test-0001"
    assert invocations.history("request-1")[0].output_classification is result.classification
    assert invocations.history("request-1")[0].temperature==audit.history("request-1")[0].temperature==.2
    assert invocations.history("request-1")[0].seed==audit.history("request-1")[0].seed==7
    assert invocations.history_by_correlation("corr-llm-test-0001")[0].request_id=="request-1"
    context=gateway._contexts.get("request-1")
    assert context==LLMInvocationContext("corr-llm-test-0001","tenant-test","llm-test-service","CLINICAL_VALIDATION","MIP-10.1","request-1",NOW)
    assert gateway._contexts.status("request-1") is InvocationContextPersistenceStatus.PERSISTED
    with pytest.raises(FrozenInstanceError):result.classification=LLMOutputClassification.DRAFT
def test_refusal_is_blocked_not_actionable():
    gateway,_,_,_,version,_=setup((response(refused=True),));result=gateway.invoke(request(version))
    assert result.classification is LLMOutputClassification.BLOCKED and not result.externally_actionable
def test_sensitive_provider_output_is_classified_and_secrets_are_not_exposed():
    gateway,_,_,_,version,_=setup((response(output_text="patient_name present"),));assert gateway.invoke(request(version)).classification is LLMOutputClassification.REVIEW_REQUIRED
    gateway,_,_,_,version,_=setup((response(output_text="sk-secret"),));result=gateway.invoke(request(version));assert result.classification is LLMOutputClassification.BLOCKED and result.output_text=="[BLOCKED]"

def test_succeeded_status_does_not_collapse_distinct_output_classifications():
    gateway,_,_,invocations,version,_=setup((response(output_text="patient_name present"),));result=gateway.invoke(request(version))
    invocation=invocations.history("request-1")[0]
    assert invocation.status is InvocationStatus.SUCCEEDED
    assert invocation.output_classification is result.classification is LLMOutputClassification.REVIEW_REQUIRED
@pytest.mark.parametrize("provider_cls,kind",[(OpenAIProviderAdapter,LLMProvider.OPENAI),(AzureOpenAIProviderAdapter,LLMProvider.AZURE_OPENAI),(AnthropicProviderAdapter,LLMProvider.ANTHROPIC),(GeminiProviderAdapter,LLMProvider.GOOGLE_GEMINI),(LocalModelProviderAdapter,LLMProvider.LOCAL)])
def test_provider_adapters_are_transport_isolated(provider_cls,kind):
    class Transport:
        def __init__(self):self.calls=[]
        def send(self,provider,request):self.calls.append((provider,request));return response()
    transport=Transport();adapter=provider_cls(transport);gateway,_,_,_,version,_=setup(provider=adapter);result=gateway.invoke(request(version,provider=kind))
    assert result.classification is LLMOutputClassification.APPROVED_FOR_REVIEW and transport.calls[0][0] is kind
def test_retry_then_success_records_retry_count():
    gateway,_,audit,invocations,version,_=setup((LLMProviderFailure("temporary"),response()),max_retries=2);gateway.invoke(request(version))
    assert audit.history("request-1")[0].retry_count==1 and invocations.history("request-1")[0].attempts==2
@pytest.mark.parametrize("failure,status,event",[(LLMProviderTimeout("timeout"),InvocationStatus.TIMEOUT,PromptAuditType.TIMEOUT),(LLMRateLimited("rate"),InvocationStatus.RATE_LIMITED,PromptAuditType.RATE_LIMIT),(LLMProviderFailure("error"),InvocationStatus.FAILED,PromptAuditType.PROVIDER_ERROR)])
def test_terminal_provider_failures_are_audited_without_prompt_or_payload(failure,status,event):
    gateway,_,audit,invocations,version,_=setup((failure,failure),max_retries=1)
    with pytest.raises(type(failure)):gateway.invoke(request(version))
    record=audit.history("request-1")[0];assert record.status is status and record.event_type is event and record.retry_count==1
    assert not hasattr(record,"prompt") and not hasattr(record,"input_dto") and invocations.history("request-1")[0].status is status
@pytest.mark.parametrize("changes",[
    {"review_policy":ReviewPolicy("bad","MIP-10.1",False,False)},
    {"review_policy":ReviewPolicy("bad","MIP-10.1",True,True)},
    {"policy_version":"wrong"},{"temperature":3},{"max_output_tokens":0}
])
def test_request_and_review_policy_fail_closed(changes):
    gateway,_,_,_,version,_=setup()
    with pytest.raises(LLMPolicyRejected):gateway.invoke(request(version,**changes))

def test_missing_invalid_and_sensitive_trusted_correlation_fail_closed():
    gateway,_,_,_,version,_=setup()
    binder=TenantContextBinder()
    with binder.bind_tenant(TenantContext("tenant","org","service","INTERNAL_SERVICE","CLINICAL_VALIDATION","MIP-10.1","bad")):
        with pytest.raises(LLMPolicyRejected,match="format"):gateway.invoke(request(version))
    with binder.bind_tenant(TenantContext("tenant","org","service","INTERNAL_SERVICE","CLINICAL_VALIDATION","MIP-10.1","pt_secret-identifier")):
        with pytest.raises(LLMPolicyRejected,match="prohibited"):gateway.invoke(request(version))
    with binder.bind_tenant(TenantContext("tenant","org","service","INTERNAL_SERVICE","CLINICAL_VALIDATION","MIP-10.1","request-1")):
        with pytest.raises(LLMPolicyRejected,match="distinct"):gateway.invoke(request(version))

def test_missing_tenant_context_fails_closed():
    from jmoraIs.tenancy import context as tenancy_context
    gateway,_,_,_,version,_=setup();token=tenancy_context._CURRENT.set(None)
    try:
        with pytest.raises(LLMPolicyRejected,match="trusted invocation context"):gateway.invoke(request(version))
    finally:tenancy_context._CURRENT.reset(token)
@pytest.mark.parametrize("invalid",[{},object(),"raw text",123])
def test_arbitrary_and_unsupported_inputs_are_rejected(invalid):
    gateway,_,_,_,version,_=setup()
    with pytest.raises(LLMPolicyRejected):gateway.invoke(request(version,input_dto=invalid))
def test_secrets_identity_and_database_entities_are_rejected():
    gateway,_,_,_,version,_=setup()
    for bad in (dto((StructuredField("api_key","value","prov"),)),dto((StructuredField("field","sk-secret","prov"),))):
        with pytest.raises(LLMPolicyRejected):gateway.invoke(request(version,input_dto=bad))
    class ORM:
        __table__=object()
    with pytest.raises(LLMPolicyRejected):gateway.invoke(request(version,input_dto=ORM()))
def test_secret_scanner_does_not_reject_opaque_clinical_reference_containing_sk_sequence():
    assert CanonicalDTOEncoder().encode(dto((StructuredField("clinical_reference","risk-1","prov"),)))
def test_prompt_is_versioned_hashed_immutable_and_tampering_fails():
    gateway,prompts,_,_,version,_=setup();assert len(version.prompt_hash)==64
    next_template=replace(template(),template_text="Second governed version");second=PromptGovernanceService(prompts,InMemoryPromptAuditRepository(),clock=lambda:NOW).register(next_template,created_by="architect")
    assert second.version==2 and second.previous_version_id==version.prompt_version_id
    prompts._items[version.prompt_version_id]=replace(version,prompt_hash="tampered")
    with pytest.raises(LLMPolicyRejected):gateway.invoke(request(version))
def test_prompt_template_with_embedded_secret_is_rejected():
    service=PromptGovernanceService(InMemoryPromptRepository(),InMemoryPromptAuditRepository(),clock=lambda:NOW)
    with pytest.raises(LLMPolicyRejected):service.register(replace(template(),template_text="Bearer secret"),created_by="architect")
def test_prompt_chain_rejects_duplicate_and_invalid_version():
    _,prompts,_,_,version,_=setup()
    with pytest.raises(PromptVersionConflict):prompts.append(version)
    with pytest.raises(PromptVersionConflict):prompts.append(replace(version,prompt_version_id="forged",version=3,previous_version_id="wrong"))
def test_supported_canonical_bounded_context_dtos():
    inp=ready_input();ortho=ortho_setup(view(finding()))[0].generate(inp).assessment;document=document_setup()[0].generate(inp,__import__("jmoraIs.medical_documents",fromlist=["DocumentType"]).DocumentType.CLINICAL_REPORT).document;defense=defense_setup()[0].generate(inp).defense
    for value in (inp,ortho,document,defense):
        gateway,_,_,_,version,_=setup(prompt_template=template((type(value).__name__,)));assert gateway.invoke(request(version,input_dto=value)).classification is LLMOutputClassification.APPROVED_FOR_REVIEW
def test_invalid_medical_document_is_rejected():
    engine,_,_,inp=document_setup(facts=());document=engine.generate(inp,__import__("jmoraIs.medical_documents",fromlist=["DocumentType"]).DocumentType.CLINICAL_REPORT).document
    gateway,_,_,_,version,_=setup(prompt_template=template(("MedicalDocument",)))
    with pytest.raises(LLMPolicyRejected):gateway.invoke(request(version,input_dto=document))
def test_invalid_provider_response_is_fail_closed():
    gateway,_,_,_,version,_=setup((response(input_tokens=-1),))
    with pytest.raises(LLMProviderFailure):gateway.invoke(request(version))

def test_context_persistence_failure_blocks_provider_and_invocation():
    gateway,_,audit,invocations,version,adapter=setup()
    class RejectingContextRepository:
        def append(self,value):raise LLMPolicyRejected("context persistence failed")
    gateway._contexts=RejectingContextRepository()
    with pytest.raises(LLMPolicyRejected,match="context persistence failed"):gateway.invoke(request(version))
    assert not adapter.requests and not invocations.history("request-1") and not audit.history("request-1")

def test_invocation_context_repository_is_append_only_and_classifies_legacy():
    repository=InMemoryLLMInvocationContextRepository()
    value=LLMInvocationContext("corr-llm-test-0001","tenant-test","llm-test-service","CLINICAL_VALIDATION","MIP-10.1","request-context",NOW)
    repository.append(value)
    with pytest.raises(PromptVersionConflict):repository.append(value)
    assert repository.history_by_correlation(value.correlation_id)==(value,)
    assert repository.status("historical-without-context") is InvocationContextPersistenceStatus.LEGACY_MISSING_INVOCATION_CONTEXT
