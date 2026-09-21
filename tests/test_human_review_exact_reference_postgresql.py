from dataclasses import replace
from datetime import datetime,timezone
import os
from uuid import uuid4
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine,text
from sqlalchemy.exc import DBAPIError
from jmoraIs.clinical.governed import HumanReviewStatus
from jmoraIs.clinical.review_governance import ReviewerRole
from jmoraIs.governed_llm_draft import PostgreSQLGovernedLLMDraftExactReferenceRepository
from jmoraIs.infrastructure.cryptographic_replay import PostgreSQLCryptographicReplayEngine,ReplayIntegrityStatus
from jmoraIs.infrastructure.tenant_database import create_tenant_runtime_engine
from jmoraIs.llm_gateway.exact_reference_persistence import PostgreSQLLLMInvocationExactReferenceRepository
from jmoraIs.llm_human_review.application import review_event_hash
from jmoraIs.llm_human_review.domain import LLMHumanReviewEvent,LLMReviewDecision
from jmoraIs.llm_human_review.exact_reference import *
from jmoraIs.llm_human_review.exact_reference_persistence import PostgreSQLHumanReviewExactReferenceRepository
from jmoraIs.llm_human_review.persistence import PostgreSQLLLMHumanReviewRepository
from jmoraIs.tenancy.context import TenantContextBinder
from jmoraIs.tenancy.domain import MissingTenantContext,TenantContext
from tests.test_governed_llm_draft_exact_reference_postgresql import persisted_draft

pytestmark=pytest.mark.integration;NOW=datetime(2026,9,6,tzinfo=timezone.utc)
def test_owner_issuance_restart_rls_append_only_and_replay():
    url=os.getenv("JMORAIS_TEST_POSTGRES_URL")
    if not url:pytest.skip("JMORAIS_TEST_POSTGRES_URL is required")
    cfg=Config("alembic.ini");cfg.set_main_option("sqlalchemy.url",url);command.upgrade(cfg,"head")
    owner=create_engine(url,future=True);suffix=uuid4().hex;tenant=TenantContext("review-ref-"+suffix,"review-org-"+suffix,"service","INTERNAL_SERVICE","CLINICAL_VALIDATION","MIP-10.1","corr-"+suffix)
    with owner.begin() as c:c.execute(text("INSERT INTO tenants(tenant_id,organization_id,display_name,status,policy_version,created_at) VALUES(:t,:o,'Review ref','ACTIVE',:p,:at)"),{"t":tenant.tenant_id,"o":tenant.organization_id,"p":tenant.policy_version,"at":NOW})
    binder=TenantContextBinder();writer=create_tenant_runtime_engine(url,runtime_role="jmorais_application_writer")
    with binder.bind_tenant(tenant):
        draft,attestor,drafts,invocation=persisted_draft(owner,writer,suffix,tenant)
        invocation_refs=PostgreSQLLLMInvocationExactReferenceRepository(writer,clock=lambda:NOW);invocation_ref=invocation_refs.reference_for(invocation)
        draft_refs=PostgreSQLGovernedLLMDraftExactReferenceRepository(writer,attestor,invocation_references=invocation_refs,clock=lambda:NOW);draft_ref=draft_refs.reference_for(draft,invocation_ref)
        unsigned=LLMHumanReviewEvent("review-"+suffix,draft.draft_id,draft.version,draft.invocation_id,draft.request_id,draft.correlation_id,draft.tenant_id,draft.upstream_artifact_reference,HumanReviewStatus.PENDING_REVIEW,HumanReviewStatus.APPROVED_BY_REVIEWER,LLMReviewDecision.APPROVE,"reviewer-"+suffix,ReviewerRole.REVIEWER,tenant.organization_id,"ST-15.1","REVIEW:test",NOW,1,None,None,"")
        event=replace(unsigned,integrity_hash=review_event_hash(unsigned));PostgreSQLLLMHumanReviewRepository(writer).append(event)
        refs=PostgreSQLHumanReviewExactReferenceRepository(writer,draft_refs,clock=lambda:NOW);reference=refs.reference_for(event,draft_ref);assert refs.get_exact(reference)==event
        with pytest.raises(HumanReviewReferenceRejected):refs.get_exact(event.review_event_id)
    writer.dispose();del event,refs,draft,drafts,invocation
    reader=create_tenant_runtime_engine(url,runtime_role="jmorais_application_reader")
    with binder.bind_tenant(tenant):
        restarted_invocations=PostgreSQLLLMInvocationExactReferenceRepository(reader);restarted_drafts=PostgreSQLGovernedLLMDraftExactReferenceRepository(reader,attestor,invocation_references=restarted_invocations)
        reread=PostgreSQLHumanReviewExactReferenceRepository(reader,restarted_drafts).get_exact(reference)
    assert reread.review_event_id==reference.review_event_id and reread.integrity_hash==reference.event_integrity_hash
    other=TenantContext("other-"+suffix,"other-org-"+suffix,"service","INTERNAL_SERVICE","CLINICAL_VALIDATION","MIP-10.1","other-corr")
    with owner.begin() as c:c.execute(text("INSERT INTO tenants(tenant_id,organization_id,display_name,status,policy_version,created_at) VALUES(:t,:o,'Other','ACTIVE',:p,:at)"),{"t":other.tenant_id,"o":other.organization_id,"p":other.policy_version,"at":NOW})
    with binder.bind_tenant(other),pytest.raises(HumanReviewReferenceRejected):PostgreSQLHumanReviewExactReferenceRepository(reader,restarted_drafts).get_exact(reference)
    with pytest.raises(MissingTenantContext):PostgreSQLHumanReviewExactReferenceRepository(reader,restarted_drafts).get_exact(reference)
    for change in ({"reference_id":"hrr_"+"f"*32},{"reviewer_id":"wrong"},{"decision":"REJECT"},{"resulting_state":"REJECTED_BY_REVIEWER"},{"policy_version":"wrong"},{"event_integrity_hash":"0"*64}):
        changed=replace(reference,**change,integrity_hash="0"*64);changed=replace(changed,integrity_hash=human_review_reference_integrity(changed))
        with binder.bind_tenant(tenant),pytest.raises(HumanReviewReferenceRejected):PostgreSQLHumanReviewExactReferenceRepository(reader,restarted_drafts).get_exact(changed)
    with pytest.raises(DBAPIError),owner.begin() as c:c.execute(text("UPDATE human_review_persisted_references SET reviewer_id='tampered' WHERE reference_id=:id"),{"id":reference.reference_id})
    with pytest.raises(DBAPIError),owner.begin() as c:c.execute(text("DELETE FROM human_review_persisted_references WHERE reference_id=:id"),{"id":reference.reference_id})
    assert PostgreSQLCryptographicReplayEngine(owner).replay_human_review_reference(reference.reference_id,tenant_id=tenant.tenant_id).integrity_status is ReplayIntegrityStatus.VALID
    reader.dispose();owner.dispose()
