import os
from dataclasses import replace
from datetime import datetime,timedelta,timezone
from uuid import uuid4

import jwt
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from cryptography.hazmat.primitives.asymmetric import rsa

from jmoraIs.clinical.governance_persistence import PostgreSQLReviewerIdentityRepository
from jmoraIs.clinical.review_governance import ReviewAuthorizationPolicy, ReviewerRole
from jmoraIs.governed_llm_draft import GovernedLLMDraftIssuanceService,PostgreSQLGovernedLLMDraftRepository
from jmoraIs.identity.configuration import OIDCProviderConfig
from jmoraIs.identity.domain import ExternalIdentityLink, IdentityLinkStatus, PrincipalType
from jmoraIs.identity.reviewer import AuthenticatedReviewerResolver
from jmoraIs.identity.session_application import CanonicalSessionSecurityService
from jmoraIs.identity.session_domain import SessionSecurityPolicy
from jmoraIs.infrastructure.identity_persistence import PostgreSQLExternalIdentityLinkRepository,PostgreSQLIdentitySecurityAudit
from jmoraIs.infrastructure.oidc_identity import OIDCIdentityProviderAdapter
from jmoraIs.infrastructure.session_persistence import PostgreSQLReplayProtectionRepository,PostgreSQLSessionRepository,PostgreSQLSessionSecurityAudit
from jmoraIs.infrastructure.tenant_database import create_tenant_runtime_engine
from jmoraIs.infrastructure.cryptographic_replay import PostgreSQLCryptographicReplayEngine,ReplayIntegrityStatus
from jmoraIs.infrastructure.managed_attestation import ManagedAttestationFactory,ManagedPersistedGatewayInputVerifier
from jmoraIs.infrastructure.persisted_gateway_input import PostgreSQLPersistedGatewayInputRepository
from jmoraIs.infrastructure.managed_secrets import EphemeralSecretProvider,InMemoryKeyMetadataRepository
from jmoraIs.infrastructure.tenant_persistence import PostgreSQLTenantRepository,PostgreSQLTenantSecurityAudit
from jmoraIs.llm_gateway import *
from jmoraIs.llm_human_review import *
from jmoraIs.audit_defense import (AuditDefenseGatewayInputIssuer,
    AuditDefenseTraceabilityService,PostgreSQLAuditDefenseEventAdapter,PostgreSQLAuditDefenseRepository,
    PostgreSQLMedicalDocumentTraceAdapter)
from jmoraIs.audit_defense.review_governance import AuditDefenseReviewGovernanceAdapter
from jmoraIs.medical_documents import DocumentType,PostgreSQLMedicalDocumentRepository
from jmoraIs.medical_documents.exact_reference_persistence import PostgreSQLMedicalDocumentExactReferenceRepository
from jmoraIs.tenancy.context import TenantContextBinder
from jmoraIs.tenancy.domain import TenantContext
from jmoraIs.tenancy.application import CanonicalTenantAuthorizationService,TrustedTenantResolutionService
from jmoraIs.secrets.domain import KeyReference,KeyState,ManagedKeyMetadata,SecretPurpose,SecretReference
from tests.test_governed_llm_draft import DRAFT_KEY, NOW
from tests.test_llm_gateway import response,template
from tests.test_medical_document_engine import setup as document_setup
from tests.test_audit_defense import setup as defense_setup

pytestmark = pytest.mark.integration


class Links:
    def __init__(self, link): self.link = link
    def get(self, provider, subject): return self.link if (provider, subject) == (self.link.provider, self.link.external_subject) else None


class Upstream:
    def constraints(self, reference): return UpstreamReviewConstraints((), None)

class Keys:
    def __init__(self,key):self.key=key
    def resolve(self,key_id,algorithm):return self.key
    def readiness(self):return type("Ready",(),{"ready":True})()


def test_review_event_postgresql_restart_rls_append_only_and_active_commit_check():
    url = os.getenv("JMORAIS_TEST_POSTGRES_URL")
    if not url: pytest.skip("JMORAIS_TEST_POSTGRES_URL is required")
    config = Config("alembic.ini"); config.set_main_option("sqlalchemy.url", url); command.upgrade(config, "head")
    owner = create_engine(url, future=True); suffix = uuid4().hex
    tenant_id, organization, principal_id = "review-" + suffix, "review-org-" + suffix, "human-" + suffix
    correlation="corr-"+suffix
    stage13_context = TenantContext(tenant_id, organization, "stage13-service-"+suffix, "INTERNAL_SERVICE", "CLINICAL_VALIDATION", "MIP-10.1", correlation)
    with owner.begin() as connection:
        connection.execute(text("INSERT INTO tenants(tenant_id,organization_id,display_name,status,policy_version,created_at) VALUES(:t,:o,'Review test','ACTIVE','MIP-10.1',:at)"), {"t": tenant_id, "o": organization, "at": NOW})
    writer = create_tenant_runtime_engine(url, runtime_role="jmorais_application_writer")
    reader = create_tenant_runtime_engine(url, runtime_role="jmorais_application_reader")
    binder = TenantContextBinder()
    draft_key=KeyReference("test-managed","stage14-draft-signing","v1",SecretPurpose.SIGNING_KEY)
    draft_secret=SecretReference("test-managed","stage14-draft-signing",SecretPurpose.SIGNING_KEY,"v1")
    secret_provider=EphemeralSecretProvider({("stage14-draft-signing","v1"):(draft_secret,DRAFT_KEY)})
    key_metadata=InMemoryKeyMetadataRepository((ManagedKeyMetadata(draft_key,KeyState.ACTIVE,NOW,NOW,None,None,"MIP-10.1"),))
    draft_attestor=ManagedAttestationFactory(secret_provider,key_metadata).draft_attestor(draft_key,actor_id="stage14-composition")
    input_key=KeyReference("test-managed","stage14-input-signing","v1",SecretPurpose.SIGNING_KEY)
    input_secret=SecretReference("test-managed","stage14-input-signing",SecretPurpose.SIGNING_KEY,"v1")
    secret_provider._values[("stage14-input-signing","v1")]=(input_secret,b"stage14-input-attestation-key-material-32")
    key_metadata.save(ManagedKeyMetadata(input_key,KeyState.ACTIVE,NOW,NOW,None,None,"MIP-10.1"))
    input_attestor=ManagedAttestationFactory(secret_provider,key_metadata).gateway_input_attestor(input_key,actor_id="stage14-composition")
    with binder.bind_tenant(stage13_context):
        document_engine,_,_,document_input=document_setup();document_input=replace(document_input,subject_reference="pt_stage14_"+suffix);document_version=document_engine.generate(document_input,DocumentType.CLINICAL_REPORT)
        documents=PostgreSQLMedicalDocumentRepository(writer);documents.append(document_version)
        initial=defense_setup()[0].generate(defense_setup()[3]);initial=replace(initial,package_id="def_"+uuid4().hex*2,stream_id="def_"+uuid4().hex*2)
        defenses=PostgreSQLAuditDefenseRepository(writer);defenses.append(initial)
        doc_owner=PostgreSQLMedicalDocumentExactReferenceRepository(writer,clock=lambda:NOW)
        trace=PostgreSQLMedicalDocumentTraceAdapter(doc_owner)
        linked=AuditDefenseTraceabilityService(trace,defenses,PostgreSQLAuditDefenseEventAdapter(writer),clock=lambda:NOW).link_stage11_document(defenses.reference_for_pre_link(initial),doc_owner.reference_for(document_version))
        final_package=defenses.get_exact(linked)
        persisted_defense_reference=defenses.reference_for(final_package)
        exact_package=defenses.get_exact(persisted_defense_reference)
        bound=AuditDefenseGatewayInputIssuer(defenses,input_attestor,clock=lambda:NOW,key_reference=input_key,document_trace_port=trace).issue_from_package(exact_package)
        prompts = PostgreSQLPromptRepository(owner)
        memory_prompts = InMemoryPromptRepository()
        prompt_template=template(("AuditDefense",));prompt_template=replace(prompt_template,template_id=prompt_template.template_id+"-"+suffix)
        prompt = PromptGovernanceService(memory_prompts, InMemoryPromptAuditRepository(), clock=lambda: NOW).register(prompt_template, created_by="owner")
        if prompts.get(prompt.prompt_version_id) is None: prompts.append(prompt)
        invocations=PostgreSQLInvocationRepository(writer);contexts=PostgreSQLLLMInvocationContextRepository(writer);prompt_audit=PostgreSQLPromptAuditRepository(writer)
        provider=MockProviderAdapter((response(output_text="Stage 14 governed review "+suffix),))
        persisted_inputs=PostgreSQLPersistedGatewayInputRepository(writer,ManagedPersistedGatewayInputVerifier(secret_provider,key_metadata))
        gateway=CanonicalLLMGateway(prompts,prompt_audit,invocations,contexts,(provider,),clock=lambda:NOW,persisted_input_attestor=input_attestor,persisted_inputs=persisted_inputs)
        policy=ReviewPolicy("human-review","MIP-10.1",True,False)
        request=LLMRequest("request-stage14-"+suffix,prompt.prompt_version_id,LLMModel(LLMProvider.MOCK,"stage14-model","1",1.0,2.0,True,"MIP-10.1"),bound,policy,.2,7,500,"MIP-10.1",NOW)
        result=gateway.invoke_persisted(request)
        persisted_drafts = PostgreSQLGovernedLLMDraftRepository(writer, draft_attestor)
        draft=GovernedLLMDraftIssuanceService(persisted_drafts,invocations,contexts,input_attestor,draft_attestor,clock=lambda:NOW).issue(bound,result,policy)
        draft_id,draft_version,draft_invocation_id,draft_correlation=draft.draft_id,draft.version,draft.invocation_id,draft.correlation_id
    writer.dispose();reader.dispose()
    del document_engine,document_input,document_version,documents,initial,defenses,trace,final_package,exact_package,bound,invocations,contexts,prompt_audit,provider,persisted_inputs,gateway,result,persisted_drafts,draft
    writer=create_tenant_runtime_engine(url,runtime_role="jmorais_application_writer")
    reader=create_tenant_runtime_engine(url,runtime_role="jmorais_application_reader")
    with binder.bind_tenant(stage13_context):
        reviewer_id="reviewer-"+suffix
        with owner.begin() as connection:connection.execute(text("INSERT INTO reviewer_identities(reviewer_id,role,status,active,organization_id,tenant_id,created_at,updated_at,authorization_policy_version) VALUES(:id,'REVIEWER','ACTIVE',true,:org,:tenant,:at,:at,'ST-15.1')"),{"id":reviewer_id,"org":organization,"tenant":tenant_id,"at":NOW})
        reviewers = PostgreSQLReviewerIdentityRepository(owner)
        link = ExternalIdentityLink(principal_id, "test-oidc", "subject-" + suffix, organization, tenant_id, IdentityLinkStatus.ACTIVE,
            PrincipalType.HUMAN, ("CLINICAL_VALIDATION",), ("clinical:review",), reviewer_id, NOW, NOW, "ST-15.1")
        links=PostgreSQLExternalIdentityLinkRepository(owner);links.create(link)
        private=rsa.generate_private_key(public_exponent=65537,key_size=2048);auth_now=datetime.now(timezone.utc).replace(microsecond=0)
        config_oidc=OIDCProviderConfig("test-oidc","https://stage14.test","stage14-audience","https://stage14.test/config","https://stage14.test/jwks",("RS256",),10,("sub","iat","exp","auth_time","roles","organization_id"),"roles","organization_id",(("reviewer","CLINICAL_REVIEWER"),),policy_version="MIP-10.1")
        token=jwt.encode({"iss":"https://stage14.test","aud":"stage14-audience","sub":link.external_subject,"iat":int(auth_now.timestamp()),"exp":int((auth_now+timedelta(hours=1)).timestamp()),"auth_time":int(auth_now.timestamp()),"roles":["reviewer"],"organization_id":organization,"sid":"session-"+suffix,"jti":"jti-"+suffix,"token_class":"SINGLE_USE"},private,algorithm="RS256",headers={"kid":"stage14-key","typ":"JWT"})
        sessions=CanonicalSessionSecurityService(PostgreSQLSessionRepository(writer),PostgreSQLReplayProtectionRepository(writer),PostgreSQLSessionSecurityAudit(writer),SessionSecurityPolicy(policy_version="MIP-10.1"),clock=lambda:auth_now)
        tenant_audit=PostgreSQLTenantSecurityAudit(owner);tenant_resolution=TrustedTenantResolutionService(PostgreSQLTenantRepository(owner),tenant_audit,clock=lambda:NOW)
        identity=OIDCIdentityProviderAdapter(config_oidc,Keys(private.public_key()),links,PostgreSQLIdentitySecurityAudit(owner),clock=lambda:auth_now,tenant_resolution=tenant_resolution,tenant_binding=binder,session_validation=sessions)
        principal=identity.validate(token,correlation)
        resolved=tenant_resolution.resolve(principal.organization_id,principal_id=principal.principal_id,correlation_id=correlation,policy_version="MIP-10.1")
        context=CanonicalTenantAuthorizationService(tenant_audit,clock=lambda:NOW).authorize(tenant=resolved,principal_id=principal.principal_id,organization_id=principal.organization_id,role=principal.roles[0],purpose="CLINICAL_VALIDATION",policy_version="MIP-10.1",correlation_id=correlation)
    with binder.bind_tenant(context):
        persisted_drafts=PostgreSQLGovernedLLMDraftRepository(reader,draft_attestor)
        audit_governance=AuditDefenseReviewGovernanceAdapter(PostgreSQLAuditDefenseRepository(reader),PostgreSQLMedicalDocumentTraceAdapter(PostgreSQLMedicalDocumentExactReferenceRepository(reader)))
        upstream_governance=UpstreamReviewGovernanceRouter({"AuditDefense":audit_governance})
        reread_draft=persisted_drafts.get(draft_id)
        reconstructed_constraints=upstream_governance.constraints(reread_draft.upstream_artifact_reference)
        reconstructed_reference=PostgreSQLAuditDefenseRepository(reader).reference_from_upstream(reread_draft.upstream_artifact_reference)
        assert reconstructed_reference==persisted_defense_reference
        assert reconstructed_constraints.generated_by is None
        reviews = PostgreSQLLLMHumanReviewRepository(writer);security_audit=PostgreSQLLLMHumanReviewSecurityAudit(writer)
        service = AuthorizedLLMHumanReviewService(persisted_drafts, persisted_drafts, PostgreSQLInvocationRepository(reader),
            PostgreSQLLLMInvocationContextRepository(reader), prompts, reviews, AuthenticatedReviewerResolver(links, reviewers), reviewers,
            upstream_governance, draft_attestor, ReviewAuthorizationPolicy("ST-15.1", False, True), clock=lambda: NOW,audit=security_audit)
        expected = service.decide(draft_id=draft_id, draft_version=draft_version, principal=principal, decision=LLMReviewDecision.APPROVE, justification_reference="REVIEW:postgres")
    writer.dispose(); reader.dispose()

    restarted_reader = create_tenant_runtime_engine(url, runtime_role="jmorais_application_reader")
    with binder.bind_tenant(context):
        reread = PostgreSQLLLMHumanReviewRepository(restarted_reader)
        assert reread.current_state(draft_id, draft_version) == expected
        assert validate_review_chain(reread.history(draft_id))
        assert reread.by_invocation(draft_invocation_id) == reread.history(draft_id)
        assert reread.by_correlation(draft_correlation) == reread.history(draft_id)
        audit_events=PostgreSQLLLMHumanReviewSecurityAudit(restarted_reader).history(context.correlation_id)
        assert validate_security_chain(audit_events) and audit_events[-1].event_type is LLMHumanReviewSecurityEventType.REVIEW_APPROVED
        assert "Governed draft output" not in repr(audit_events)
    replay=PostgreSQLCryptographicReplayEngine(owner)
    for table,stream in (("governed_llm_draft_lifecycle_events",draft_id),("llm_human_review_events",draft_id),("llm_human_review_security_events",context.correlation_id)):
        report=replay.replay_trust_stream(table,stream,tenant_id=tenant_id)
        assert report.integrity_status is ReplayIntegrityStatus.VALID and report.verified_events,report.failed_events
    other = TenantContext("other-" + suffix, "other-org-" + suffix, "other", "CLINICAL_REVIEWER", "CLINICAL_VALIDATION", "ST-15.1", context.correlation_id)
    with owner.begin() as connection:
        connection.execute(text("INSERT INTO tenants(tenant_id,organization_id,display_name,status,policy_version,created_at) VALUES(:t,:o,'Other','ACTIVE','ST-15.1',:at)"), {"t": other.tenant_id, "o": other.organization_id, "at": NOW})
    with binder.bind_tenant(other):
        assert PostgreSQLLLMHumanReviewRepository(restarted_reader).history(draft_id) == ()
        assert PostgreSQLLLMHumanReviewSecurityAudit(restarted_reader).history(context.correlation_id) == ()
    with pytest.raises(DBAPIError), owner.begin() as connection:
        connection.execute(text("UPDATE llm_human_review_events SET policy_version='tampered' WHERE draft_id=:id"), {"id": draft_id})
    with pytest.raises(DBAPIError), owner.begin() as connection:
        connection.execute(text("DELETE FROM llm_human_review_events WHERE draft_id=:id"), {"id": draft_id})
    with pytest.raises(DBAPIError), owner.begin() as connection:
        connection.execute(text("UPDATE llm_human_review_security_events SET reason_code='tampered' WHERE correlation_id=:id"), {"id": context.correlation_id})

    # Simulate privileged storage tampering.  Normal application roles remain
    # protected by append-only triggers; replay must independently distrust the
    # migration owner and detect every affected critical stream.
    with owner.begin() as connection:
        connection.execute(text("ALTER TABLE governed_llm_draft_lifecycle_events DISABLE TRIGGER ALL"))
        connection.execute(text("""UPDATE governed_llm_draft_lifecycle_events
            SET payload=jsonb_set(payload,'{reason_reference}','\"tampered\"'::jsonb),previous_hash=:hash
            WHERE tenant_id=:tenant AND draft_id=:draft AND stream_position=1"""), {"hash":"0"*64,"tenant":tenant_id,"draft":draft_id})
        connection.execute(text("ALTER TABLE governed_llm_draft_lifecycle_events ENABLE TRIGGER ALL"))
        connection.execute(text("ALTER TABLE llm_human_review_events DISABLE TRIGGER ALL"))
        connection.execute(text("""DELETE FROM llm_human_review_events
            WHERE tenant_id=:tenant AND draft_id=:draft"""), {"tenant":tenant_id,"draft":draft_id})
        connection.execute(text("ALTER TABLE llm_human_review_events ENABLE TRIGGER ALL"))
        connection.execute(text("ALTER TABLE llm_human_review_security_events DISABLE TRIGGER ALL"))
        connection.execute(text("""DELETE FROM llm_human_review_security_events
            WHERE tenant_id=:tenant AND correlation_id=:correlation AND stream_position=2"""), {"tenant":tenant_id,"correlation":context.correlation_id})
        connection.execute(text("ALTER TABLE llm_human_review_security_events ENABLE TRIGGER ALL"))
    tampered=(
        replay.replay_trust_stream("governed_llm_draft_lifecycle_events",draft_id,tenant_id=tenant_id),
        replay.replay_trust_stream("llm_human_review_events",draft_id,tenant_id=tenant_id),
        replay.replay_trust_stream("llm_human_review_security_events",context.correlation_id,tenant_id=tenant_id),
    )
    assert all(report.integrity_status is ReplayIntegrityStatus.TAMPERED for report in tampered)
    reasons={reason for report in tampered for failure in report.failed_events for reason in failure.reasons}
    assert {"MODIFIED_PAYLOAD","BROKEN_PREVIOUS_HASH","BROKEN_STREAM_POSITION","STREAM_COMPLETENESS_FAILURE"}.issubset(reasons)
    global_report=replay.replay_all()
    assert global_report.overall_decision is ReplayIntegrityStatus.TAMPERED
    assert all(any(table in report.stream for report in global_report.streams) for table in (
        "governed_llm_draft_lifecycle_events","llm_human_review_events","llm_human_review_security_events"))
    restarted_reader.dispose(); owner.dispose()
