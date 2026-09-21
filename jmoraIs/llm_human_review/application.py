from __future__ import annotations
import json
from dataclasses import asdict,replace
from hashlib import sha256
from uuid import uuid4
from jmoraIs.clinical.governed import HumanReviewStatus
from jmoraIs.clinical.review_governance import ReviewAuthorizationPolicy,ReviewerRole
from jmoraIs.governed_llm_draft import DraftReviewStatus,GovernedLLMDraft,GovernedLLMDraftLifecycleStatus,validate_draft_integrity
from jmoraIs.llm_gateway.domain import LLMOutputClassification
from jmoraIs.identity.domain import AuthenticatedPrincipal,PrincipalType
from jmoraIs.tenancy.context import current_tenant_context
from .domain import *

def _hash(value):
    material=asdict(value);material["integrity_hash"]=""
    return sha256(json.dumps(material,sort_keys=True,separators=(",",":"),default=str).encode()).hexdigest()
def review_event_hash(value):return _hash(value)
def security_event_hash(value):return _hash(value)
def validate_review_chain(events):
    for i,event in enumerate(events):
        previous=events[i-1] if i else None
        if event.stream_position!=i+1 or event.integrity_hash!=review_event_hash(event):return False
        if previous is None:
            if event.predecessor_event_id is not None or event.previous_hash is not None or event.prior_state is not HumanReviewStatus.PENDING_REVIEW:return False
        elif event.predecessor_event_id!=previous.review_event_id or event.previous_hash!=previous.integrity_hash or event.prior_state is not previous.resulting_state:return False
    return True
def validate_security_chain(events):
    return all(event.stream_position==i+1 and event.previous_hash==(events[i-1].integrity_hash if i else None) and event.integrity_hash==security_event_hash(event) for i,event in enumerate(events))

class AuthorizedLLMHumanReviewService:
    PURPOSES={"CLINICAL_REVIEW","CLINICAL_VALIDATION"}
    TARGETS={LLMReviewDecision.APPROVE:HumanReviewStatus.APPROVED_BY_REVIEWER,LLMReviewDecision.REJECT:HumanReviewStatus.REJECTED_BY_REVIEWER,LLMReviewDecision.REQUEST_CLARIFICATION:HumanReviewStatus.NEEDS_CLARIFICATION}
    def __init__(self,drafts,lifecycle,invocations,contexts,prompts,reviews,reviewer_resolver,reviewer_authorization,upstream_governance,draft_attestor,policy:ReviewAuthorizationPolicy,*,clock,audit=None):
        self._drafts=drafts;self._lifecycle=lifecycle;self._invocations=invocations;self._contexts=contexts;self._prompts=prompts;self._reviews=reviews;self._resolver=reviewer_resolver;self._authorization=reviewer_authorization;self._upstream=upstream_governance;self._attestor=draft_attestor;self._policy=policy;self._clock=clock;self._audit=audit
    def decide(self,*,draft_id,draft_version,principal:AuthenticatedPrincipal,decision:LLMReviewDecision,justification_reference:str):
        tenant=current_tenant_context();self._audit_event(LLMHumanReviewSecurityEventType.REVIEW_ATTEMPT,draft_id,draft_version,principal,None,"ATTEMPT","REVIEW_REQUESTED")
        try:return self._decide(draft_id,draft_version,principal,decision,justification_reference,tenant)
        except Exception as exc:
            message=str(exc).casefold();kind=LLMHumanReviewSecurityEventType.REVIEW_AUTHORIZATION_DENIED
            if "tenant" in message:kind=LLMHumanReviewSecurityEventType.TENANT_MISMATCH
            elif "purpose" in message:kind=LLMHumanReviewSecurityEventType.PURPOSE_REJECTED
            elif "integrity" in message:kind=LLMHumanReviewSecurityEventType.DRAFT_INTEGRITY_REJECTED
            elif "lifecycle" in message or "active" in message:kind=LLMHumanReviewSecurityEventType.DRAFT_LIFECYCLE_REJECTED
            elif "transition" in message:kind=LLMHumanReviewSecurityEventType.INVALID_TRANSITION
            elif "reviewer" in message:kind=LLMHumanReviewSecurityEventType.REVIEWER_REJECTED
            self._audit_event(kind,draft_id,draft_version,principal,None,"DENIED",type(exc).__name__);raise
    def _decide(self,draft_id,draft_version,principal,decision,justification_reference,tenant):
        if not isinstance(principal,AuthenticatedPrincipal) or principal.principal_type is not PrincipalType.HUMAN or not principal.session_id:raise LLMHumanReviewRejected("authenticated human session is required")
        if principal.tenant_id!=tenant.tenant_id or principal.organization_id!=tenant.organization_id or principal.principal_id!=tenant.principal_id:raise LLMHumanReviewRejected("principal tenant context mismatch")
        if tenant.purpose not in self.PURPOSES or tenant.purpose not in principal.allowed_purposes:raise LLMHumanReviewRejected("review purpose is not authorized")
        draft=self._drafts.get(draft_id)
        if not isinstance(draft,GovernedLLMDraft) or draft.version!=draft_version:raise LLMHumanReviewRejected("exact persisted GovernedLLMDraft is required")
        if not validate_draft_integrity(draft,self._attestor):raise LLMHumanReviewRejected("draft integrity is invalid")
        if draft.tenant_id!=tenant.tenant_id:raise LLMHumanReviewRejected("draft tenant mismatch")
        if draft.output_classification not in {LLMOutputClassification.APPROVED_FOR_REVIEW.value,LLMOutputClassification.REVIEW_REQUIRED.value,LLMOutputClassification.DRAFT.value}:raise LLMHumanReviewRejected("draft classification is not review eligible")
        if draft.review_status not in {DraftReviewStatus.PENDING_REVIEW,DraftReviewStatus.REVIEW_REQUIRED}:raise LLMHumanReviewRejected("draft status is not review eligible")
        self._validate_stage13(draft)
        identity=self._resolver.resolve(principal)
        if not self._authorization.may_review(identity):raise LLMHumanReviewRejected("reviewer is not authorized")
        if identity.tenant_id!=tenant.tenant_id or identity.organization_id!=tenant.organization_id:raise LLMHumanReviewRejected("reviewer scope mismatch")
        if identity.authorization_policy_version!=self._policy.policy_version:raise LLMHumanReviewRejected("reviewer policy is stale")
        self._audit_event(LLMHumanReviewSecurityEventType.REVIEW_AUTHORIZED,draft_id,draft_version,principal,identity,"AUTHORIZED","POLICY_ACCEPTED",draft)
        if not justification_reference.strip():raise LLMHumanReviewRejected("review justification reference is required")
        constraints=self._upstream.constraints(draft.upstream_artifact_reference)
        if decision is LLMReviewDecision.APPROVE:
            if constraints.generated_by==identity.reviewer_id and not self._policy.allow_self_approval:raise LLMHumanReviewRejected("self-approval is prohibited")
            if constraints.critical_conflicts and self._policy.critical_conflict_requires_senior and identity.role is ReviewerRole.REVIEWER:raise LLMHumanReviewRejected("critical conflict requires senior reviewer")
        history=self._reviews.history(draft_id)
        if not validate_review_chain(history):raise LLMHumanReviewRejected("review history integrity is invalid")
        prior=history[-1].resulting_state if history else HumanReviewStatus.PENDING_REVIEW;target=self.TARGETS[decision]
        allowed={HumanReviewStatus.PENDING_REVIEW:{HumanReviewStatus.APPROVED_BY_REVIEWER,HumanReviewStatus.REJECTED_BY_REVIEWER,HumanReviewStatus.NEEDS_CLARIFICATION},HumanReviewStatus.NEEDS_CLARIFICATION:{HumanReviewStatus.REJECTED_BY_REVIEWER}}
        if target not in allowed.get(prior,set()):raise LLMHumanReviewRejected("invalid review transition")
        if self._lifecycle.current_status(draft_id,draft_version) is not GovernedLLMDraftLifecycleStatus.ACTIVE:raise LLMHumanReviewRejected("draft lifecycle is not ACTIVE")
        previous=history[-1] if history else None;position=len(history)+1;at=self._clock();identifier="llm_review_"+sha256((draft_id+"|"+str(position)+"|"+decision.value+"|"+identity.reviewer_id).encode()).hexdigest()
        unsigned=LLMHumanReviewEvent(identifier,draft_id,draft_version,draft.invocation_id,draft.request_id,draft.correlation_id,draft.tenant_id,draft.upstream_artifact_reference,prior,target,decision,identity.reviewer_id,identity.role,identity.organization_id,self._policy.policy_version,justification_reference,at,position,previous.review_event_id if previous else None,previous.integrity_hash if previous else None,"")
        event=replace(unsigned,integrity_hash=review_event_hash(unsigned));self._reviews.append(event)
        kind={LLMReviewDecision.APPROVE:LLMHumanReviewSecurityEventType.REVIEW_APPROVED,LLMReviewDecision.REJECT:LLMHumanReviewSecurityEventType.REVIEW_REJECTED,LLMReviewDecision.REQUEST_CLARIFICATION:LLMHumanReviewSecurityEventType.REVIEW_CLARIFICATION_REQUESTED}[decision]
        self._audit_event(kind,draft_id,draft_version,principal,identity,"SUCCESS",decision.value,draft)
        return LLMHumanReviewState(draft_id,draft_version,target,event.review_event_id,False)
    def _validate_stage13(self,draft):
        invocations=self._invocations.history(draft.request_id)
        if len(invocations)!=1:raise LLMHumanReviewRejected("persisted invocation linkage is invalid")
        invocation=invocations[0];context=self._contexts.get(draft.request_id);prompt=self._prompts.get(draft.prompt_version)
        if invocation.invocation_id!=draft.invocation_id or invocation.upstream_reference!=draft.upstream_artifact_reference or invocation.reviewable_content_hash!=draft.reviewable_content_hash:raise LLMHumanReviewRejected("Stage-13 invocation linkage is invalid")
        if context is None or context.correlation_id!=draft.correlation_id or context.tenant_id!=draft.tenant_id:raise LLMHumanReviewRejected("invocation context linkage is invalid")
        if prompt is None or prompt.prompt_version_id!=draft.prompt_version:raise LLMHumanReviewRejected("PromptVersion linkage is invalid")
    def _audit_event(self,kind,draft_id,draft_version,principal,identity,result,reason,draft=None):
        if self._audit is None:return
        tenant=current_tenant_context();history=self._audit.history(tenant.correlation_id)
        if not validate_security_chain(history):raise LLMHumanReviewRejected("security audit history integrity is invalid")
        previous=history[-1] if history else None
        unsigned=LLMHumanReviewSecurityEvent("review_security_"+uuid4().hex,kind,draft_id,draft_version,getattr(draft,"invocation_id",None),getattr(draft,"request_id",None),tenant.correlation_id,tenant.tenant_id,getattr(principal,"principal_id",None),getattr(identity,"reviewer_id",None),getattr(getattr(identity,"role",None),"value",None),tenant.organization_id,result,reason,self._policy.policy_version,self._clock(),len(history)+1,previous.integrity_hash if previous else None,"")
        self._audit.append(replace(unsigned,integrity_hash=security_event_hash(unsigned)))
