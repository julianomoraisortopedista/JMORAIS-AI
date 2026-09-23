from dataclasses import FrozenInstanceError, replace
from datetime import timedelta

import pytest

from jmoraIs.clinical.governed import HumanReviewStatus
from jmoraIs.clinical.review_governance import InMemoryReviewerAuthorizationAdapter, ReviewAuthorizationPolicy, ReviewerIdentity, ReviewerRole, ReviewerStatus
from jmoraIs.governed_llm_draft import GovernedDraftAttestor, GovernedLLMDraftLifecycleService, GovernedLLMDraftLifecycleStatus
from jmoraIs.identity.domain import AuthenticatedPrincipal, ExternalIdentityLink, IdentityLinkStatus, PrincipalType
from jmoraIs.identity.reviewer import AuthenticatedReviewerResolver
from jmoraIs.llm_human_review import *
from jmoraIs.tenancy.context import TenantContextBinder
from jmoraIs.tenancy.domain import TenantContext
from tests.test_governed_llm_draft import DRAFT_KEY, DRAFT_KEY_REFERENCE, NOW, setup_draft


class Links:
    def __init__(self, link): self.link = link
    def get(self, provider, subject):
        return self.link if (provider, subject) == (self.link.provider, self.link.external_subject) else None


class PromptLookup:
    def __init__(self, prompt_id): self.prompt_id = prompt_id
    def get(self, prompt_id):
        return type("PersistedPrompt", (), {"prompt_version_id": self.prompt_id})() if prompt_id == self.prompt_id else None


class Upstream:
    def __init__(self, conflicts=(), generated_by=None): self.value = UpstreamReviewConstraints(conflicts, generated_by)
    def constraints(self, reference): return self.value


def principal(kind=PrincipalType.HUMAN, tenant="tenant-test", organization="org-test", purpose="CLINICAL_VALIDATION"):
    return AuthenticatedPrincipal("human-1", "subject-1", "test-oidc", organization, tenant, ("CLINICAL_REVIEWER",), NOW,
        "OIDC", "session-1", "ST-15.1", NOW, NOW + timedelta(hours=1), kind, (purpose,), ("clinical:review",))


def build(*, role=ReviewerRole.REVIEWER, reviewer_status=ReviewerStatus.ACTIVE, conflicts=(), generated_by=None, audit=None):
    issuer, drafts, bound, response, policy, invocations, contexts = setup_draft()
    draft = issuer.issue(bound, response, policy)
    reviewer = ReviewerIdentity("reviewer-1", role, status=reviewer_status, organization_id="org-test", tenant_id="tenant-test",
        created_at=NOW, updated_at=NOW, authorization_policy_version="ST-15.1")
    reviewers = InMemoryReviewerAuthorizationAdapter((reviewer,))
    link = ExternalIdentityLink("human-1", "test-oidc", "subject-1", "org-test", "tenant-test", IdentityLinkStatus.ACTIVE,
        PrincipalType.HUMAN, ("CLINICAL_VALIDATION",), ("clinical:review",), "reviewer-1", NOW, NOW, "ST-15.1")
    reviews = InMemoryLLMHumanReviewRepository(drafts)
    service = AuthorizedLLMHumanReviewService(drafts, drafts, invocations, contexts, PromptLookup(draft.prompt_version), reviews,
        AuthenticatedReviewerResolver(Links(link), reviewers), reviewers, Upstream(conflicts, generated_by), GovernedDraftAttestor(DRAFT_KEY,key_reference=DRAFT_KEY_REFERENCE),
        ReviewAuthorizationPolicy("ST-15.1", False, True), clock=lambda: NOW, audit=audit)
    return service, reviews, drafts, draft


@pytest.fixture(autouse=True)
def tenant():
    with TenantContextBinder().bind_tenant(TenantContext("tenant-test", "org-test", "human-1", "CLINICAL_REVIEWER", "CLINICAL_VALIDATION", "ST-15.1", "corr-draft-test-0001")):
        yield


def test_authorized_human_approval_is_immutable_append_only_and_not_actionable():
    service, reviews, _, draft = build()
    state = service.decide(draft_id=draft.draft_id, draft_version=1, principal=principal(), decision=LLMReviewDecision.APPROVE, justification_reference="REVIEW:complete")
    event = reviews.history(draft.draft_id)[0]
    assert state.status is HumanReviewStatus.APPROVED_BY_REVIEWER and state.externally_actionable is False
    assert event.reviewer_role is ReviewerRole.REVIEWER and validate_review_chain((event,))
    with pytest.raises(FrozenInstanceError): event.resulting_state = HumanReviewStatus.REJECTED_BY_REVIEWER
    with pytest.raises(LLMHumanReviewRejected): reviews.append(event)

def test_security_audit_is_metadata_only_hash_linked_and_records_success_and_denial():
    audit=InMemoryLLMHumanReviewSecurityAudit();service,_,_,draft=build(audit=audit)
    service.decide(draft_id=draft.draft_id,draft_version=1,principal=principal(),decision=LLMReviewDecision.APPROVE,justification_reference="REVIEW:complete")
    events=audit.history("corr-draft-test-0001")
    assert [x.event_type for x in events]==[LLMHumanReviewSecurityEventType.REVIEW_ATTEMPT,LLMHumanReviewSecurityEventType.REVIEW_AUTHORIZED,LLMHumanReviewSecurityEventType.REVIEW_APPROVED]
    assert validate_security_chain(events)
    assert "Governed draft output" not in repr(events) and "reviewable_content" not in repr(events)
    audit=InMemoryLLMHumanReviewSecurityAudit();service,_,_,draft=build(audit=audit)
    with pytest.raises(LLMHumanReviewRejected):service.decide(draft_id=draft.draft_id,draft_version=1,principal=principal(PrincipalType.SERVICE),decision=LLMReviewDecision.APPROVE,justification_reference="x")
    assert audit.history("corr-draft-test-0001")[-1].result=="DENIED"


@pytest.mark.parametrize("decision,target", [(LLMReviewDecision.REJECT, HumanReviewStatus.REJECTED_BY_REVIEWER), (LLMReviewDecision.REQUEST_CLARIFICATION, HumanReviewStatus.NEEDS_CLARIFICATION)])
def test_rejection_and_clarification(decision, target):
    service, _, _, draft = build()
    assert service.decide(draft_id=draft.draft_id, draft_version=1, principal=principal(), decision=decision, justification_reference="REVIEW:reason").status is target


def test_service_principal_wrong_tenant_purpose_and_missing_draft_fail_closed():
    service, _, _, draft = build()
    for actor in (principal(PrincipalType.SERVICE), principal(purpose="OTHER")):
        with pytest.raises(LLMHumanReviewRejected): service.decide(draft_id=draft.draft_id, draft_version=1, principal=actor, decision=LLMReviewDecision.APPROVE, justification_reference="x")
    with pytest.raises(LLMHumanReviewRejected): service.decide(draft_id="missing", draft_version=1, principal=principal(), decision=LLMReviewDecision.APPROVE, justification_reference="x")


@pytest.mark.parametrize("target", [GovernedLLMDraftLifecycleStatus.SUPERSEDED, GovernedLLMDraftLifecycleStatus.INVALIDATED])
def test_non_active_lifecycle_blocks_review(target):
    service, _, drafts, draft = build()
    GovernedLLMDraftLifecycleService(drafts, drafts, GovernedDraftAttestor(DRAFT_KEY,key_reference=DRAFT_KEY_REFERENCE), clock=lambda: NOW).transition(draft.draft_id, 1, target, reason_reference="POLICY:block", actor_reference="policy", policy_version="ST-15.1")
    with pytest.raises(LLMHumanReviewRejected, match="ACTIVE"):
        service.decide(draft_id=draft.draft_id, draft_version=1, principal=principal(), decision=LLMReviewDecision.APPROVE, justification_reference="x")


def test_tampering_inactive_reviewer_self_approval_and_critical_conflict_fail_closed():
    service, _, drafts, draft = build()
    drafts._items[draft.draft_id] = replace(draft, reviewable_content="tampered")
    with pytest.raises(LLMHumanReviewRejected, match="integrity"):
        service.decide(draft_id=draft.draft_id, draft_version=1, principal=principal(), decision=LLMReviewDecision.APPROVE, justification_reference="x")
    for kwargs in ({"reviewer_status": ReviewerStatus.SUSPENDED}, {"generated_by": "reviewer-1"}, {"conflicts": ("CRITICAL_CONFLICT",)}):
        service, _, _, draft = build(**kwargs)
        with pytest.raises(Exception): service.decide(draft_id=draft.draft_id, draft_version=1, principal=principal(), decision=LLMReviewDecision.APPROVE, justification_reference="x")
