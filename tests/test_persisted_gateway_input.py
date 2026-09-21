from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone

import pytest

from jmoraIs.gateway_input import (
    HMACPersistedGatewayInputAttestor, PersistedGatewayInput,
)
from jmoraIs.infrastructure.persisted_gateway_input import InMemoryPersistedGatewayInputRepository
from jmoraIs.secrets.domain import KeyReference,SecretPurpose
from jmoraIs.llm_gateway import (
    CanonicalLLMGateway, InMemoryInvocationRepository,
    InMemoryLLMInvocationContextRepository, InMemoryPromptAuditRepository,
    InMemoryPromptRepository, LLMPolicyRejected, MockProviderAdapter,
    PromptGovernanceService,
)
from jmoraIs.medical_documents.gateway_input import MedicalDocumentGatewayInputIssuer
from jmoraIs.tenancy.context import TenantContextBinder
from jmoraIs.tenancy.domain import TenantContext
from tests.test_llm_gateway import request, response, template
from tests.test_medical_document_engine import setup as document_setup

NOW=datetime(2026,8,13,tzinfo=timezone.utc)
KEY=b"persisted-gateway-input-test-key-32-bytes-minimum"
KEY_REFERENCE=KeyReference("memory","gateway-input","v1",SecretPurpose.SIGNING_KEY)


def _setup():
    document_engine,repository,_,reasoning_input=document_setup()
    version=document_engine.generate(reasoning_input,__import__("jmoraIs.medical_documents",fromlist=["DocumentType"]).DocumentType.CLINICAL_REPORT)
    attestor=HMACPersistedGatewayInputAttestor(KEY)
    bound=MedicalDocumentGatewayInputIssuer(repository,attestor,clock=lambda:NOW,key_reference=KEY_REFERENCE).issue(version.document_stream_id,version.version)
    prompts=InMemoryPromptRepository();audit=InMemoryPromptAuditRepository();invocations=InMemoryInvocationRepository();contexts=InMemoryLLMInvocationContextRepository()
    prompt=PromptGovernanceService(prompts,audit,clock=lambda:NOW).register(template(("MedicalDocument",)),created_by="architect")
    provider=MockProviderAdapter((response(),))
    gateway=CanonicalLLMGateway(prompts,audit,invocations,contexts,(provider,),clock=lambda:NOW,persisted_input_attestor=attestor,persisted_inputs=InMemoryPersistedGatewayInputRepository(attestor))
    return gateway,invocations,prompt,bound,version


@pytest.fixture(autouse=True)
def tenant():
    with TenantContextBinder().bind_tenant(TenantContext("tenant-test","org-test","service","INTERNAL_SERVICE","CLINICAL_VALIDATION","MIP-10.1","corr-input-test-0001")):
        yield


def test_owner_issued_input_is_atomic_immutable_and_persisted_on_invocation():
    gateway,invocations,prompt,bound,version=_setup()
    result=gateway.invoke_persisted(request(prompt,input_dto=bound))
    reference=invocations.history("request-1")[0].upstream_reference
    assert result.output_text=="Governed draft output"
    assert reference.artifact_type=="MedicalDocument"
    assert (reference.artifact_id,reference.artifact_version)==(version.document_stream_id,version.version)
    assert bound.dto is version.document
    with pytest.raises(FrozenInstanceError):bound.dto_hash="changed"


def test_manual_forgery_tampering_type_mismatch_and_raw_dto_fail_closed():
    gateway,_,prompt,bound,_=_setup()
    forged=replace(bound,attestation="0"*64)
    with pytest.raises(LLMPolicyRejected,match="attestation"):gateway.invoke_persisted(request(prompt,input_dto=forged))
    mismatched=replace(bound,reference=replace(bound.reference,artifact_type="AuditDefense"))
    with pytest.raises(LLMPolicyRejected):gateway.invoke_persisted(request(prompt,input_dto=mismatched))
    with pytest.raises(LLMPolicyRejected,match="requires PersistedGatewayInput"):gateway.invoke_persisted(request(prompt,input_dto=bound.dto))


def test_tenant_version_integrity_and_nonexistent_version_fail_closed():
    gateway,_,prompt,bound,version=_setup()
    for altered in (
        replace(bound,reference=replace(bound.reference,artifact_version=version.version+1)),
        replace(bound,reference=replace(bound.reference,integrity_reference="bad")),
        replace(bound,dto_hash="bad"),
    ):
        with pytest.raises(LLMPolicyRejected):gateway.invoke_persisted(request(prompt,input_dto=altered))
    with TenantContextBinder().bind_tenant(TenantContext("tenant-other","org-other","service","INTERNAL_SERVICE","CLINICAL_VALIDATION","MIP-10.1","corr-input-other-001")):
        with pytest.raises(LLMPolicyRejected):gateway.invoke_persisted(request(prompt,input_dto=bound))

def test_owner_issuer_rejects_nonexistent_version_instead_of_substituting_latest():
    document_engine,repository,_,reasoning_input=document_setup()
    value=document_engine.generate(reasoning_input,__import__("jmoraIs.medical_documents",fromlist=["DocumentType"]).DocumentType.CLINICAL_REPORT)
    issuer=MedicalDocumentGatewayInputIssuer(repository,HMACPersistedGatewayInputAttestor(KEY),clock=lambda:NOW)
    with pytest.raises(Exception,match="exact persisted MedicalDocumentVersion"):
        issuer.issue(value.document_stream_id,value.version+1)


def test_canonical_structured_dto_is_not_eligible_for_persisted_review_flow():
    gateway,_,prompt,_,_= _setup()
    from tests.test_llm_gateway import dto
    fake=PersistedGatewayInput(dto(),pytest.importorskip("jmoraIs.gateway_input").UpstreamArtifactReference("CanonicalStructuredDTO","x",1,"tenant-test","hash","MIP-10.1","caller"),"hash",NOW,"signature")
    with pytest.raises(LLMPolicyRejected):gateway.invoke_persisted(request(prompt,input_dto=fake))
