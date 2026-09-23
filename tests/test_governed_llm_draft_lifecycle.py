from dataclasses import FrozenInstanceError,replace
from hashlib import sha256
import pytest
from jmoraIs.governed_llm_draft import *
from jmoraIs.governed_llm_draft.application import _integrity_hash
from jmoraIs.tenancy.context import TenantContextBinder
from jmoraIs.tenancy.domain import TenantContext
from tests.test_governed_llm_draft import NOW,DRAFT_KEY,DRAFT_KEY_REFERENCE,setup_draft
@pytest.fixture(autouse=True)
def tenant():
    with TenantContextBinder().bind_tenant(TenantContext("tenant-test","org-test","service","INTERNAL_SERVICE","CLINICAL_VALIDATION","MIP-10.1","corr-draft-test-0001")):yield

def test_issuance_atomically_establishes_active_genesis():
    service,repository,bound,result,policy,_,_=setup_draft();draft=service.issue(bound,result,policy);history=repository.lifecycle_history(draft.draft_id)
    assert repository.current_status(draft.draft_id,1) is GovernedLLMDraftLifecycleStatus.ACTIVE
    assert len(history)==1 and history[0].stream_position==1 and history[0].prior_status is None
    assert history[0].previous_hash is None and validate_lifecycle_chain(history)

def test_invalidation_is_append_only_and_irreversible():
    service,repository,bound,result,policy,_,_=setup_draft();draft=service.issue(bound,result,policy)
    lifecycle=GovernedLLMDraftLifecycleService(repository,repository,GovernedDraftAttestor(DRAFT_KEY,key_reference=DRAFT_KEY_REFERENCE),clock=lambda:NOW)
    event=lifecycle.transition(draft.draft_id,1,GovernedLLMDraftLifecycleStatus.INVALIDATED,reason_reference="POLICY:invalid",actor_reference="policy-engine",policy_version="MIP-10.1")
    assert event.stream_position==2 and repository.current_status(draft.draft_id,1) is GovernedLLMDraftLifecycleStatus.INVALIDATED
    with pytest.raises(DraftBoundaryRejected):lifecycle.transition(draft.draft_id,1,GovernedLLMDraftLifecycleStatus.ACTIVE,reason_reference="reactivate",actor_reference="actor",policy_version="MIP-10.1")
    with pytest.raises(FrozenInstanceError):event.resulting_status=GovernedLLMDraftLifecycleStatus.ACTIVE

def test_new_version_atomically_supersedes_prior_active_version():
    service,repository,bound,result,policy,_,_=setup_draft();first=service.issue(bound,result,policy);attestor=GovernedDraftAttestor(DRAFT_KEY,key_reference=DRAFT_KEY_REFERENCE)
    content=first.reviewable_content+" v2";content_hash=sha256(content.encode()).hexdigest();draft_id="draft_"+sha256((first.draft_stream_id+"|2|"+content_hash).encode()).hexdigest()
    unsigned=replace(first,draft_id=draft_id,version=2,predecessor=first.draft_id,reviewable_content=content,reviewable_content_hash=content_hash,integrity_hash="",issuance_attestation="")
    with_integrity=replace(unsigned,integrity_hash=_integrity_hash(unsigned));second=replace(with_integrity,issuance_attestation=attestor.sign(with_integrity))
    active=lifecycle_event(second,GovernedLLMDraftLifecycleStatus.ACTIVE,"CANONICAL_ISSUANCE","issuer","MIP-10.1",NOW)
    superseded=lifecycle_event(first,GovernedLLMDraftLifecycleStatus.SUPERSEDED,"REPLACED_BY:"+second.draft_id,"issuer","MIP-10.1",NOW,repository.lifecycle_history(first.draft_id))
    repository.append_with_lifecycle(second,active,superseded)
    assert repository.current_status(first.draft_id,1) is GovernedLLMDraftLifecycleStatus.SUPERSEDED
    assert repository.current_status(second.draft_id,2) is GovernedLLMDraftLifecycleStatus.ACTIVE
    assert repository.current_active(first.draft_stream_id)==second and repository.get(first.draft_id)==first

def test_missing_forged_wrong_version_duplicate_and_broken_chain_rejected():
    service,repository,bound,result,policy,_,_=setup_draft();draft=service.issue(bound,result,policy);lifecycle=GovernedLLMDraftLifecycleService(repository,repository,GovernedDraftAttestor(DRAFT_KEY,key_reference=DRAFT_KEY_REFERENCE),clock=lambda:NOW)
    with pytest.raises(DraftBoundaryRejected):lifecycle.transition("missing",1,GovernedLLMDraftLifecycleStatus.INVALIDATED,reason_reference="x",actor_reference="x",policy_version="p")
    with pytest.raises(DraftBoundaryRejected):lifecycle.transition(draft.draft_id,2,GovernedLLMDraftLifecycleStatus.INVALIDATED,reason_reference="x",actor_reference="x",policy_version="p")
    genesis=repository.lifecycle_history(draft.draft_id)[0]
    for bad in (genesis,replace(genesis,lifecycle_event_id="forged",stream_position=2),replace(genesis,integrity_hash="0"*64)):
        with pytest.raises((DraftBoundaryRejected,DraftVersionConflict)):repository.append_lifecycle(bad)
