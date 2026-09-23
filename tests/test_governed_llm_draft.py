from dataclasses import FrozenInstanceError,replace
from datetime import datetime,timezone
from hashlib import sha256
import pytest
from jmoraIs.governed_llm_draft import *
from jmoraIs.gateway_input import HMACPersistedGatewayInputAttestor
from jmoraIs.infrastructure.persisted_gateway_input import InMemoryPersistedGatewayInputRepository
from jmoraIs.secrets.domain import KeyReference,SecretPurpose
from jmoraIs.llm_gateway import *
from jmoraIs.medical_documents.gateway_input import MedicalDocumentGatewayInputIssuer
from jmoraIs.tenancy.context import TenantContextBinder
from jmoraIs.tenancy.domain import TenantContext
from tests.test_llm_gateway import request,response,template
from tests.test_medical_document_engine import setup as document_setup
NOW=datetime(2026,8,13,tzinfo=timezone.utc);INPUT_KEY=b"input-attestation-key-for-governed-draft-tests";DRAFT_KEY=b"draft-attestation-key-for-governed-draft-tests"
DRAFT_KEY_REFERENCE=KeyReference("memory","draft-signing","v1",SecretPurpose.SIGNING_KEY)
KEY_REFERENCE=KeyReference("memory","gateway-input","v1",SecretPurpose.SIGNING_KEY)
@pytest.fixture(autouse=True)
def tenant():
    with TenantContextBinder().bind_tenant(TenantContext("tenant-test","org-test","service","INTERNAL_SERVICE","CLINICAL_VALIDATION","MIP-10.1","corr-draft-test-0001")):yield
def setup_draft(provider_response=None,request_id="request-1"):
    engine,documents,_,inp=document_setup();version=engine.generate(inp,__import__("jmoraIs.medical_documents",fromlist=["DocumentType"]).DocumentType.CLINICAL_REPORT)
    input_attestor=HMACPersistedGatewayInputAttestor(INPUT_KEY);bound=MedicalDocumentGatewayInputIssuer(documents,input_attestor,clock=lambda:NOW,key_reference=KEY_REFERENCE).issue(version.document_stream_id,1)
    prompts=InMemoryPromptRepository();audits=InMemoryPromptAuditRepository();invocations=InMemoryInvocationRepository();contexts=InMemoryLLMInvocationContextRepository();prompt=PromptGovernanceService(prompts,audits,clock=lambda:NOW).register(template(("MedicalDocument",)),created_by="owner")
    gateway=CanonicalLLMGateway(prompts,audits,invocations,contexts,(MockProviderAdapter((provider_response or response(),)),),clock=lambda:NOW,persisted_input_attestor=input_attestor,persisted_inputs=InMemoryPersistedGatewayInputRepository(input_attestor))
    policy=ReviewPolicy("human-review","MIP-10.1",True,False);result=gateway.invoke_persisted(request(prompt,input_dto=bound,review_policy=policy,request_id=request_id))
    draft_attestor=GovernedDraftAttestor(DRAFT_KEY,key_reference=DRAFT_KEY_REFERENCE);repository=InMemoryGovernedLLMDraftRepository(draft_attestor);service=GovernedLLMDraftIssuanceService(repository,invocations,contexts,input_attestor,draft_attestor,clock=lambda:NOW)
    return service,repository,bound,result,policy,invocations,contexts
def test_eligible_gateway_output_issues_immutable_reviewable_draft():
    service,repository,bound,result,policy,_,_=setup_draft();draft=service.issue(bound,result,policy)
    assert repository.get(draft.draft_id)==draft and draft.reviewable_content==result.output_text
    assert draft.reviewable_content_hash==sha256(draft.reviewable_content.encode()).hexdigest()==result.reviewable_content_hash
    assert draft.upstream_artifact_reference==bound.reference and draft.version==1 and draft.predecessor is None
    assert draft.review_status is DraftReviewStatus.PENDING_REVIEW and not draft.review_policy.external_actionability_allowed
    with pytest.raises(FrozenInstanceError):draft.reviewable_content="changed"
def test_tampered_content_hash_linkage_and_manual_fabrication_are_rejected():
    service,repository,bound,result,policy,invocations,_=setup_draft()
    for bad in (replace(result,output_text="tampered"),replace(result,reviewable_content_hash="0"*64),replace(result,request_id="other")):
        with pytest.raises(DraftBoundaryRejected):service.issue(bound,bad,policy)
    draft=service.issue(bound,result,policy)
    with pytest.raises(DraftBoundaryRejected):repository.append(replace(draft,draft_id="manual",issuance_attestation=""))
    forged_invocation=replace(invocations.history(result.request_id)[0],upstream_reference=replace(bound.reference,artifact_id="other"))
    invocations._items=[forged_invocation]
    with pytest.raises(DraftBoundaryRejected,match="upstream"):service.issue(bound,result,policy)
def test_tenant_mismatch_and_blocked_output_fail_closed():
    service,_,bound,result,policy,_,_=setup_draft()
    with TenantContextBinder().bind_tenant(TenantContext("other","other-org","service","INTERNAL_SERVICE","CLINICAL_VALIDATION","MIP-10.1","corr-draft-other-001")):
        with pytest.raises(DraftBoundaryRejected):service.issue(bound,result,policy)
    service,_,bound,result,policy,_,_=setup_draft(response(refused=True))
    with pytest.raises(DraftBoundaryRejected,match="eligible|blocked"):service.issue(bound,result,policy)
def test_redaction_occurs_before_independent_content_hash():
    redactor=ReviewableContentRedactor();content=redactor.redact("contact user@example.com token=unsafe")
    assert "example.com" not in content and "unsafe" not in content and content.count("[REDACTED]")==2
