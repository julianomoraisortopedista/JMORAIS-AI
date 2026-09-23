from __future__ import annotations

import os
from dataclasses import replace
from datetime import datetime,timedelta,timezone
from uuid import uuid4

import jwt
import pytest
from alembic import command
from alembic.config import Config
from cryptography.hazmat.primitives.asymmetric import rsa
from jmoraIs.medical_documents.exact_reference_persistence import PostgreSQLMedicalDocumentExactReferenceRepository
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from jmoraIs.identity.configuration import OIDCProviderConfig
from jmoraIs.identity.domain import ExternalIdentityLink, IdentityLinkStatus, PrincipalType
from jmoraIs.identity.session_application import CanonicalSessionSecurityService
from jmoraIs.identity.session_domain import SessionSecurityPolicy
from jmoraIs.infrastructure.identity_persistence import PostgreSQLExternalIdentityLinkRepository, PostgreSQLIdentitySecurityAudit
from jmoraIs.infrastructure.oidc_identity import OIDCIdentityProviderAdapter
from jmoraIs.infrastructure.session_persistence import PostgreSQLReplayProtectionRepository, PostgreSQLSessionRepository, PostgreSQLSessionSecurityAudit
from jmoraIs.infrastructure.tenant_database import create_tenant_runtime_engine
from jmoraIs.infrastructure.managed_attestation import ManagedAttestationFactory,ManagedPersistedGatewayInputVerifier
from jmoraIs.infrastructure.managed_secrets import EphemeralSecretProvider,InMemoryKeyMetadataRepository
from jmoraIs.infrastructure.persisted_gateway_input import PostgreSQLPersistedGatewayInputRepository
from jmoraIs.secrets.domain import KeyReference,KeyState,ManagedKeyMetadata,SecretPurpose,SecretReference
from jmoraIs.gateway_input import HMACPersistedGatewayInputAttestor
from jmoraIs.governed_llm_draft import GovernedDraftAttestor,GovernedLLMDraftIssuanceService,GovernedLLMDraftLifecycleService,GovernedLLMDraftLifecycleStatus,PostgreSQLGovernedLLMDraftRepository
from tests.test_governed_llm_draft import DRAFT_KEY, DRAFT_KEY_REFERENCE
from jmoraIs.llm_gateway import *
from jmoraIs.audit_defense import (AuditDefenseGatewayInputIssuer,AuditDefenseGatewayInputResolver,
    AuditDefenseTraceabilityService,PostgreSQLAuditDefenseEventAdapter,PostgreSQLAuditDefenseRepository,
    PostgreSQLMedicalDocumentTraceAdapter)
from jmoraIs.infrastructure.persisted_gateway_input import PersistedGatewayInputTrustService
from jmoraIs.medical_documents import DocumentType,PostgreSQLMedicalDocumentRepository
from jmoraIs.tenancy.context import TenantContextBinder
from jmoraIs.tenancy.domain import TenantContext
from tests.test_llm_gateway import response
from tests.test_audit_defense import setup as defense_setup
from tests.test_medical_document_engine import setup as document_setup

pytestmark=pytest.mark.integration


class _StaticSigningKeys:
    def __init__(self,key):self._key=key
    def resolve(self,key_id,algorithm):return self._key
    def readiness(self):
        from jmoraIs.api.security import ReadinessCheck
        return ReadinessCheck("stage13_test_keys",True,"AVAILABLE")


def _oidc_config():
    return OIDCProviderConfig("stage13-oidc","https://stage13.test","jmorais-stage13",
        "https://stage13.test/configuration","https://stage13.test/jwks",("RS256",),10,
        ("sub","iat","exp","auth_time","roles","organization_id"),"roles","organization_id",
        (("svc","INTERNAL_SERVICE"),),policy_version="MIP-10.1")


def test_stage13_real_persisted_audit_defense_gateway_restart_equivalence():
    url=os.getenv("JMORAIS_TEST_POSTGRES_URL")
    if not url:pytest.skip("JMORAIS_TEST_POSTGRES_URL is required")
    config=Config("alembic.ini");config.set_main_option("sqlalchemy.url",url);command.upgrade(config,"head")
    owner=create_engine(url,future=True);suffix=uuid4().hex;binder=TenantContextBinder();now=datetime.now(timezone.utc).replace(microsecond=0)

    tenant,organization="stage13-"+suffix,"org-stage13-"+suffix
    with owner.begin() as connection:
        connection.execute(text("INSERT INTO tenants(tenant_id,organization_id,display_name,status,policy_version,created_at) VALUES(:t,:o,'Stage 13 canonical','ACTIVE','MIP-10.1',:at)"),{"t":tenant,"o":organization,"at":now})

    principal_id="stage13-principal-"+suffix;subject="stage13-subject-"+suffix;correlation="corr-stage13-final-"+suffix
    link=ExternalIdentityLink(principal_id,"stage13-oidc",subject,organization,tenant,IdentityLinkStatus.ACTIVE,
        PrincipalType.SERVICE,("CLINICAL_VALIDATION",),("llm:invoke",),None,now,now,"MIP-10.1")
    PostgreSQLExternalIdentityLinkRepository(owner).create(link)
    security_writer=create_tenant_runtime_engine(url,runtime_role="jmorais_application_writer")
    session_service=CanonicalSessionSecurityService(PostgreSQLSessionRepository(security_writer),
        PostgreSQLReplayProtectionRepository(security_writer),PostgreSQLSessionSecurityAudit(security_writer),
        SessionSecurityPolicy(policy_version="MIP-10.1"),clock=lambda:now)
    private=rsa.generate_private_key(public_exponent=65537,key_size=2048);issued=now-timedelta(seconds=1);expires=now+timedelta(minutes=5)
    token=jwt.encode({"iss":"https://stage13.test","aud":"jmorais-stage13","sub":subject,
        "iat":int(issued.timestamp()),"exp":int(expires.timestamp()),"auth_time":int(issued.timestamp()),
        "roles":["svc"],"organization_id":organization,"sid":"session-"+suffix,"jti":"jti-"+suffix},
        private,algorithm="RS256",headers={"kid":"stage13-key","typ":"JWT"})
    identity=OIDCIdentityProviderAdapter(_oidc_config(),_StaticSigningKeys(private.public_key()),
        PostgreSQLExternalIdentityLinkRepository(owner),PostgreSQLIdentitySecurityAudit(owner),clock=lambda:now,
        tenant_binding=binder,session_validation=session_service)
    authenticated=identity.validate(token,correlation)
    assert authenticated.principal_id==principal_id and authenticated.tenant_id==tenant
    trusted=TenantContext(tenant,organization,authenticated.principal_id,authenticated.roles[0],
        "CLINICAL_VALIDATION","MIP-10.1",correlation)

    stage12_writer=create_tenant_runtime_engine(url,runtime_role="jmorais_application_writer")
    with binder.bind_tenant(trusted):
        document=document_setup()[0].generate(document_setup()[3],DocumentType.CLINICAL_REPORT)
        document=replace(document,version_id="doc_"+uuid4().hex*2,document_stream_id="doc_"+uuid4().hex*2)
        documents=PostgreSQLMedicalDocumentRepository(stage12_writer);documents.append(document)
        initial=defense_setup()[0].generate(defense_setup()[3])
        initial=replace(initial,package_id="def_"+uuid4().hex*2,stream_id="def_"+uuid4().hex*2)
        defenses=PostgreSQLAuditDefenseRepository(stage12_writer);defenses.append(initial)
        document_owner=PostgreSQLMedicalDocumentExactReferenceRepository(stage12_writer,clock=lambda:now)
        trace=PostgreSQLMedicalDocumentTraceAdapter(document_owner)
        linked=AuditDefenseTraceabilityService(trace,defenses,PostgreSQLAuditDefenseEventAdapter(stage12_writer),clock=lambda:now).link_stage11_document(defenses.reference_for_pre_link(initial),document_owner.reference_for(document))
        final_package=defenses.get_exact(linked)
        persisted_defense_reference=defenses.reference_for(final_package)
    stage12_writer.dispose()
    del document,documents,initial,final_package,defenses,trace,stage12_writer

    reader=create_tenant_runtime_engine(url,runtime_role="jmorais_application_reader")
    input_key_bytes=b"stage13-persisted-input-attestation-key-32-bytes"
    input_key=KeyReference("test-managed","stage13-input-"+suffix,"v1",SecretPurpose.SIGNING_KEY)
    input_secret=SecretReference("test-managed",input_key.key_id,SecretPurpose.SIGNING_KEY,"v1")
    secret_provider=EphemeralSecretProvider({(input_key.key_id,"v1"):(input_secret,input_key_bytes)})
    key_metadata=InMemoryKeyMetadataRepository((ManagedKeyMetadata(input_key,KeyState.ACTIVE,now,now,None,None,"MIP-10.1"),))
    attestor=ManagedAttestationFactory(secret_provider,key_metadata).gateway_input_attestor(input_key,actor_id="stage13-composition")
    with binder.bind_tenant(trusted):
        defenses=PostgreSQLAuditDefenseRepository(reader)
        trace=PostgreSQLMedicalDocumentTraceAdapter(PostgreSQLMedicalDocumentExactReferenceRepository(reader))
        exact_final_package=defenses.get_exact(persisted_defense_reference)
        assert trace.resolve_exact(exact_final_package.stage11_document_reference)
        persisted_input=AuditDefenseGatewayInputIssuer(defenses,attestor,clock=lambda:now,key_reference=input_key,document_trace_port=trace).issue_from_package(exact_final_package)
    upstream_dto=exact_final_package.defense

    prompts=PostgreSQLPromptRepository(owner);registration_audit=PostgreSQLPromptAuditRepository(owner)
    template=PromptTemplate("stage13-template-"+suffix,"Stage 13 governed document draft","CLINICAL_VALIDATION",
        "Produce a non-actionable structured draft for human review.",(type(upstream_dto).__name__,),
        "audit-defense-draft-v1","MIP-10.1")
    prompt=PromptGovernanceService(prompts,registration_audit,clock=lambda:now).register(template,created_by=principal_id)
    writer=create_tenant_runtime_engine(url,runtime_role="jmorais_application_writer")
    contexts=PostgreSQLLLMInvocationContextRepository(writer);invocations=PostgreSQLInvocationRepository(writer);audits=PostgreSQLPromptAuditRepository(writer)
    provider=MockProviderAdapter((response(provider_request_id="mock-stage13-"+suffix),response(provider_request_id="mock-stage13-v2-"+suffix,output_text="Governed draft output version 2")))
    input_verifier=ManagedPersistedGatewayInputVerifier(secret_provider,key_metadata)
    persisted_inputs=PostgreSQLPersistedGatewayInputRepository(writer,input_verifier)
    gateway=CanonicalLLMGateway(prompts,audits,invocations,contexts,(provider,),clock=lambda:now,persisted_input_attestor=attestor,persisted_inputs=persisted_inputs)
    draft_attestor=GovernedDraftAttestor(DRAFT_KEY,key_reference=DRAFT_KEY_REFERENCE)
    drafts=PostgreSQLGovernedLLMDraftRepository(writer,draft_attestor)
    request_id="request-stage13-"+suffix
    request_value=LLMRequest(request_id,prompt.prompt_version_id,
        LLMModel(LLMProvider.MOCK,"stage13-mock-model","1",1.0,2.0,True,"MIP-10.1"),persisted_input,
        ReviewPolicy("stage13-human-review","MIP-10.1",True,False),.25,314,600,"MIP-10.1",now)
    with binder.bind_tenant(trusted):
        gateway_result=gateway.invoke_persisted(request_value)
        original_context=contexts.get(request_id);original_invocation=invocations.history(request_id)[0];original_audit=audits.history(request_id)[0]
        original_draft=GovernedLLMDraftIssuanceService(drafts,invocations,contexts,attestor,draft_attestor,clock=lambda:now).issue(persisted_input,gateway_result,request_value.review_policy)
        request2=replace(request_value,request_id="request-stage13-v2-"+suffix)
        response2=gateway.invoke_persisted(request2)
        second_draft=GovernedLLMDraftIssuanceService(drafts,invocations,contexts,attestor,draft_attestor,clock=lambda:now).issue(persisted_input,response2,request2.review_policy)
    assert len(provider.requests)==2 and provider.requests[0].request_id==request_id
    assert gateway_result.classification is LLMOutputClassification.APPROVED_FOR_REVIEW
    assert not gateway_result.externally_actionable
    assert original_invocation.output_classification is gateway_result.classification
    assert original_invocation.status is InvocationStatus.SUCCEEDED
    assert original_invocation.temperature==original_audit.temperature==.25
    assert original_invocation.seed==original_audit.seed==314
    assert original_context.request_id==original_invocation.request_id==original_audit.request_id
    assert original_context.correlation_id==original_invocation.correlation_id==original_audit.correlation_id
    assert original_context.policy_version==original_invocation.policy_version==original_audit.policy_version=="MIP-10.1"
    assert original_context.tenant_id==tenant and original_context.principal_id==principal_id
    assert original_context.purpose==template.purpose=="CLINICAL_VALIDATION" and original_context.issued_at==now
    assert original_invocation.prompt_version_id==original_audit.prompt_version_id==prompt.prompt_version_id
    assert original_invocation.request_hash==original_audit.request_hash and original_invocation.response_hash==original_audit.response_hash
    assert original_invocation.upstream_reference==persisted_input.reference
    assert original_invocation.token_usage==original_audit.token_usage and original_invocation.cost==original_audit.cost
    assert original_draft.reviewable_content==gateway_result.output_text
    assert original_draft.reviewable_content_hash==gateway_result.reviewable_content_hash==original_invocation.reviewable_content_hash
    with binder.bind_tenant(trusted):
        assert drafts.current_status(original_draft.draft_id,original_draft.version) is GovernedLLMDraftLifecycleStatus.SUPERSEDED
        assert drafts.current_status(second_draft.draft_id,second_draft.version) is GovernedLLMDraftLifecycleStatus.ACTIVE

    with owner.connect() as connection:
        stored=connection.execute(text("SELECT i.tenant_id AS invocation_tenant,a.tenant_id AS audit_tenant,i.payload::text AS invocation_payload,a.payload::text AS audit_payload FROM llm_invocations i JOIN llm_prompt_audit a ON a.request_id=i.request_id WHERE i.invocation_id=:id"),{"id":original_invocation.invocation_id}).mappings().one()
    assert stored["invocation_tenant"]==stored["audit_tenant"]==tenant
    persisted_text=(stored["invocation_payload"]+stored["audit_payload"]).casefold()
    for forbidden in (upstream_dto.subject_reference.casefold(),"patient_name","cpf","raw_prompt","raw_response","bearer ","password","api_key","managed_secret"):
        assert forbidden not in persisted_text

    context_value,invocation_value,audit_value,prompt_value,draft_value,second_draft_value=original_context,original_invocation,original_audit,prompt,original_draft,second_draft
    upstream_reference=persisted_input.reference
    del exact_final_package,upstream_dto,persisted_input,request_value,request2,gateway_result,response2,original_draft,second_draft,gateway,provider,contexts,invocations,audits,drafts,prompts,registration_audit,session_service,identity,authenticated,token,link,defenses,trace
    reader.dispose();writer.dispose();security_writer.dispose();owner.dispose()

    restarted_owner=create_engine(url,future=True)
    restarted_reader=create_tenant_runtime_engine(url,runtime_role="jmorais_application_reader")
    restarted_writer=create_tenant_runtime_engine(url,runtime_role="jmorais_application_writer")
    restarted_contexts=PostgreSQLLLMInvocationContextRepository(restarted_reader)
    restarted_invocations=PostgreSQLInvocationRepository(restarted_reader);restarted_audits=PostgreSQLPromptAuditRepository(restarted_reader)
    restarted_prompts=PostgreSQLPromptRepository(restarted_owner)
    restarted_drafts=PostgreSQLGovernedLLMDraftRepository(restarted_reader,draft_attestor)
    restarted_draft_writer=PostgreSQLGovernedLLMDraftRepository(restarted_writer,draft_attestor)
    with binder.bind_tenant(trusted):
        reread_context=restarted_contexts.get(request_id);reread_invocation=restarted_invocations.history(request_id)[0]
        reread_audit=restarted_audits.history(request_id)[0];reread_prompt=restarted_prompts.get(prompt_value.prompt_version_id)
        reread_draft=restarted_drafts.get(draft_value.draft_id)
        reread_second_draft=restarted_drafts.get(second_draft_value.draft_id)
        restarted_defenses=PostgreSQLAuditDefenseRepository(restarted_reader)
        restarted_trace=PostgreSQLMedicalDocumentTraceAdapter(PostgreSQLMedicalDocumentExactReferenceRepository(restarted_reader))
        restarted_records=PostgreSQLPersistedGatewayInputRepository(restarted_reader,input_verifier)
        persisted_record=restarted_records.get_by_invocation(reread_invocation.invocation_id)
        reconstructed=PersistedGatewayInputTrustService(restarted_records,input_verifier,
            {"AuditDefense":AuditDefenseGatewayInputResolver(restarted_defenses,restarted_trace)}).verify_and_resolve(
                persisted_record.persisted_gateway_input_id)
        exact_package_after_restart=restarted_defenses.get_exact(persisted_defense_reference)
        exact_document_after_restart=restarted_trace.resolve_exact(exact_package_after_restart.stage11_document_reference)
    assert reread_context==context_value and reread_context is not context_value
    assert reread_invocation==invocation_value and reread_invocation is not invocation_value
    assert reread_invocation.upstream_reference==upstream_reference
    assert persisted_record.upstream_artifact_reference.artifact_type=="AuditDefense"
    assert reconstructed.dto==exact_package_after_restart.defense
    assert persisted_record.upstream_artifact_reference.artifact_id==exact_package_after_restart.stream_id
    assert persisted_record.upstream_artifact_reference.artifact_version==exact_package_after_restart.version
    assert exact_document_after_restart.document.document_id==exact_package_after_restart.stage11_document_reference.document_id
    assert reread_audit==audit_value and reread_audit is not audit_value
    assert reread_prompt==prompt_value and reread_prompt is not prompt_value
    assert reread_draft==draft_value and reread_draft is not draft_value
    assert (reread_draft.version,reread_draft.predecessor,reread_draft.invocation_id,reread_draft.upstream_artifact_reference,reread_draft.provenance)==(draft_value.version,draft_value.predecessor,invocation_value.invocation_id,upstream_reference,draft_value.provenance)
    assert reread_second_draft==second_draft_value
    with binder.bind_tenant(trusted):
        assert restarted_drafts.current_status(draft_value.draft_id,draft_value.version) is GovernedLLMDraftLifecycleStatus.SUPERSEDED
        assert restarted_drafts.current_status(second_draft_value.draft_id,second_draft_value.version) is GovernedLLMDraftLifecycleStatus.ACTIVE
    with binder.bind_tenant(trusted):
        invalidation_event=GovernedLLMDraftLifecycleService(restarted_drafts,restarted_draft_writer,draft_attestor,clock=lambda:now).transition(second_draft_value.draft_id,second_draft_value.version,GovernedLLMDraftLifecycleStatus.INVALIDATED,reason_reference="POLICY:stage13-test",actor_reference="policy-engine",policy_version="MIP-10.1")
        assert restarted_drafts.current_status(second_draft_value.draft_id,second_draft_value.version) is GovernedLLMDraftLifecycleStatus.INVALIDATED
    assert (reread_context.request_id,reread_context.correlation_id,reread_context.tenant_id,reread_context.principal_id,
        reread_context.purpose,reread_context.policy_version,reread_context.issued_at)==(
        request_id,correlation,tenant,principal_id,"CLINICAL_VALIDATION","MIP-10.1",now)
    assert (reread_invocation.output_classification,reread_invocation.temperature,reread_invocation.seed,
        reread_invocation.provider,reread_invocation.model_id,reread_invocation.prompt_version_id,
        reread_invocation.request_hash,reread_invocation.response_hash,reread_invocation.token_usage,
        reread_invocation.cost,reread_invocation.status,reread_invocation.policy_version)==(
        invocation_value.output_classification,.25,314,LLMProvider.MOCK,"stage13-mock-model",prompt_value.prompt_version_id,
        invocation_value.request_hash,invocation_value.response_hash,invocation_value.token_usage,
        invocation_value.cost,InvocationStatus.SUCCEEDED,"MIP-10.1")

    other=TenantContext("other-"+suffix,"other-org-"+suffix,"other-principal","INTERNAL_SERVICE",
        "CLINICAL_VALIDATION","MIP-10.1",correlation)
    with restarted_owner.begin() as connection:
        connection.execute(text("INSERT INTO tenants(tenant_id,organization_id,display_name,status,policy_version,created_at) VALUES(:t,:o,'Stage 13 other','ACTIVE','MIP-10.1',:at)"),{"t":other.tenant_id,"o":other.organization_id,"at":now})
    with binder.bind_tenant(other):
        assert restarted_contexts.get(request_id) is None
        assert restarted_invocations.history(request_id)==() and restarted_audits.history(request_id)==()
        assert restarted_drafts.get(draft_value.draft_id) is None
    assert restarted_contexts.get(request_id) is None
    assert restarted_invocations.history(request_id)==() and restarted_audits.history(request_id)==()
    with restarted_owner.connect() as connection:
        assert not connection.execute(text("SELECT rolbypassrls FROM pg_roles WHERE rolname='jmorais_application_reader'")).scalar_one()
    for table,column,value in (("llm_invocation_contexts","request_id",request_id),("llm_invocations","invocation_id",invocation_value.invocation_id),("llm_prompt_audit","event_id",audit_value.event_id),("governed_llm_drafts","draft_id",draft_value.draft_id),("governed_llm_draft_lifecycle_events","lifecycle_event_id",invalidation_event.lifecycle_event_id)):
        with pytest.raises(DBAPIError),restarted_owner.begin() as connection:
            connection.execute(text(f"UPDATE {table} SET policy_version='ALTERED' WHERE {column}=:id"),{"id":value})
        with pytest.raises(DBAPIError),restarted_owner.begin() as connection:
            connection.execute(text(f"DELETE FROM {table} WHERE {column}=:id"),{"id":value})
    restarted_reader.dispose();restarted_writer.dispose();restarted_owner.dispose()
