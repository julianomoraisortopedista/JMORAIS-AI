from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field, replace
from datetime import date, datetime, timezone
from enum import Enum
from typing import Protocol
from uuid import uuid4

from jmoraIs.appraisal.governed import GovernedEvidence, GovernedEvidenceRepository

from .governed import (
    GovernedClinicalRecommendation,
    GovernedDecisionAuditPort,
    HumanReviewStatus,
    ReviewTransitionRejected,
    _event,
)


class ReviewerRole(str, Enum):
    REVIEWER = "REVIEWER"
    SENIOR_REVIEWER = "SENIOR_REVIEWER"
    ADMINISTRATOR = "ADMINISTRATOR"


class ReviewerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    SUSPENDED = "SUSPENDED"


@dataclass(frozen=True)
class ReviewerIdentity:
    reviewer_id: str
    role: ReviewerRole
    active: bool = True
    status: ReviewerStatus = ReviewerStatus.ACTIVE
    organization_id: str = "default"
    tenant_id: str = "default"
    created_at: datetime = dataclass_field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = dataclass_field(default_factory=lambda: datetime.now(timezone.utc))
    authorization_policy_version: str = "ST-22.1"

    def __post_init__(self) -> None:
        if not self.reviewer_id.strip() or not self.organization_id.strip() or not self.tenant_id.strip():
            raise ValueError("reviewer, organization and tenant identifiers are required")
        if self.updated_at < self.created_at:
            raise ValueError("reviewer updated_at cannot precede created_at")


class ReviewerAuthorizationPort(Protocol):
    def resolve(self, reviewer_id: str) -> ReviewerIdentity | None: ...
    def may_review(self, identity: ReviewerIdentity) -> bool: ...


class InMemoryReviewerAuthorizationAdapter:
    def __init__(self, identities: tuple[ReviewerIdentity, ...]) -> None:
        self._identities = {item.reviewer_id: item for item in identities}

    def resolve(self, reviewer_id: str) -> ReviewerIdentity | None:
        return self._identities.get(reviewer_id)

    def may_review(self, identity: ReviewerIdentity) -> bool:
        return identity.active and identity.status == ReviewerStatus.ACTIVE and identity.role in set(ReviewerRole)


@dataclass(frozen=True)
class ReviewAuthorizationPolicy:
    policy_version: str = "ST-15.1"
    allow_self_approval: bool = False
    critical_conflict_requires_senior: bool = True


class AuthorizedRecommendationReviewService:
    def __init__(self, authorization: ReviewerAuthorizationPort, audit: GovernedDecisionAuditPort,
                 policy: ReviewAuthorizationPolicy, *, clock=None, monitoring=None) -> None:
        self._authorization, self._audit, self._policy = authorization, audit, policy
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._monitoring = monitoring

    def transition(self, *, case_id: str, recommendation: GovernedClinicalRecommendation,
                   target: HumanReviewStatus, reviewer_id: str, justification: str,
                   generated_by: str | None = None) -> GovernedClinicalRecommendation:
        identity = self._authorization.resolve(reviewer_id)
        if identity is None or not self._authorization.may_review(identity):
            if self._monitoring is not None:
                self._monitoring.unauthorized_review(reviewer_id)
            raise ReviewTransitionRejected("reviewer is not authorized")
        if not justification.strip():
            raise ReviewTransitionRejected("review justification is required")
        if target == HumanReviewStatus.APPROVED_BY_REVIEWER:
            if generated_by == reviewer_id and not self._policy.allow_self_approval:
                raise ReviewTransitionRejected("self-approval is prohibited by policy")
            critical = {"CONFLICTING_RECOMMENDATIONS", "CONFLICTING_ORGANIZATIONS"}.intersection(
                recommendation.explanation.conflicts
            )
            if critical and self._policy.critical_conflict_requires_senior and identity.role == ReviewerRole.REVIEWER:
                raise ReviewTransitionRejected("critical conflict requires a senior reviewer")
        allowed = {
            HumanReviewStatus.PENDING_REVIEW: {HumanReviewStatus.APPROVED_BY_REVIEWER,
                HumanReviewStatus.REJECTED_BY_REVIEWER, HumanReviewStatus.NEEDS_CLARIFICATION},
            HumanReviewStatus.NEEDS_CLARIFICATION: {HumanReviewStatus.PENDING_REVIEW,
                HumanReviewStatus.REJECTED_BY_REVIEWER},
        }
        if target not in allowed.get(recommendation.review_status, set()):
            raise ReviewTransitionRejected("invalid review transition")
        history = self._audit.history(case_id)
        event = _event(case_id, "AUTHORIZED_REVIEW_STATE_CHANGED", self._clock(),
            recommendation.governed_evidence_ids, (recommendation.recommendation_id,), (),
            recommendation.explanation.conflicts, (), recommendation.review_status.value,
            target.value, identity.reviewer_id, identity.role.value, self._policy.policy_version,
            justification, history[-1].event_hash if history else None)
        self._audit.append(event)
        explanation = replace(recommendation.explanation, human_review_status=target)
        return replace(recommendation, review_status=target, explanation=explanation,
            externally_actionable=target == HumanReviewStatus.APPROVED_BY_REVIEWER)


class ConflictAdjudicationState(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    RESOLVED = "RESOLVED"
    UNRESOLVED = "UNRESOLVED"
    ESCALATED = "ESCALATED"


@dataclass(frozen=True)
class ConflictAdjudicationEvent:
    event_id: str
    conflict_id: str
    case_id: str
    state: ConflictAdjudicationState
    directions: tuple[str, ...]
    actor_id: str
    actor_role: str
    justification: str
    policy_version: str
    occurred_at: datetime
    previous_event_hash: str | None
    event_hash: str


class ConflictAdjudicationRepository(Protocol):
    def append(self, event: ConflictAdjudicationEvent) -> None: ...
    def history(self, conflict_id: str) -> tuple[ConflictAdjudicationEvent, ...]: ...


class ConflictAdjudicationService:
    _ALLOWED = {
        None: {ConflictAdjudicationState.OPEN},
        ConflictAdjudicationState.OPEN: {ConflictAdjudicationState.UNDER_REVIEW, ConflictAdjudicationState.ESCALATED},
        ConflictAdjudicationState.UNDER_REVIEW: {ConflictAdjudicationState.RESOLVED,
            ConflictAdjudicationState.UNRESOLVED, ConflictAdjudicationState.ESCALATED},
        ConflictAdjudicationState.UNRESOLVED: {ConflictAdjudicationState.UNDER_REVIEW,
            ConflictAdjudicationState.ESCALATED},
        ConflictAdjudicationState.ESCALATED: {ConflictAdjudicationState.UNDER_REVIEW,
            ConflictAdjudicationState.RESOLVED, ConflictAdjudicationState.UNRESOLVED},
    }

    def __init__(self, repository: ConflictAdjudicationRepository,
                 authorization: ReviewerAuthorizationPort, *, policy_version="ST-15.1", clock=None) -> None:
        self._repository, self._authorization = repository, authorization
        self._policy_version = policy_version
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def transition(self, *, conflict_id: str, case_id: str, target: ConflictAdjudicationState,
                   directions: tuple[str, ...], reviewer_id: str, justification: str):
        identity = self._authorization.resolve(reviewer_id)
        if identity is None or not self._authorization.may_review(identity):
            raise ReviewTransitionRejected("reviewer is not authorized")
        history = self._repository.history(conflict_id)
        previous = history[-1].state if history else None
        if target not in self._ALLOWED.get(previous, set()) or not justification.strip():
            raise ReviewTransitionRejected("invalid conflict adjudication transition")
        if target == ConflictAdjudicationState.RESOLVED and identity.role == ReviewerRole.REVIEWER:
            raise ReviewTransitionRejected("conflict resolution requires a senior reviewer")
        from .governed import _hash
        occurred_at, event_id = self._clock(), uuid4().hex
        previous_hash = history[-1].event_hash if history else None
        payload = {"event_id": event_id, "conflict_id": conflict_id, "case_id": case_id,
            "state": target.value, "directions": list(directions), "actor_id": identity.reviewer_id,
            "actor_role": identity.role.value, "justification": justification,
            "policy_version": self._policy_version, "occurred_at": occurred_at.isoformat(),
            "previous_event_hash": previous_hash}
        event = ConflictAdjudicationEvent(event_id, conflict_id, case_id, target, directions,
            identity.reviewer_id, identity.role.value, justification, self._policy_version,
            occurred_at, previous_hash, _hash(payload))
        self._repository.append(event)
        return event


class GovernedEvidenceLifecycleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    SUPERSEDED = "SUPERSEDED"
    INVALIDATED = "INVALIDATED"


class ReevaluationTrigger(str, Enum):
    PACKAGE_REVOKED = "PACKAGE_REVOKED"
    GUIDELINE_EXPIRED = "GUIDELINE_EXPIRED"
    GUIDELINE_WITHDRAWN = "GUIDELINE_WITHDRAWN"
    GUIDELINE_SUPERSEDED = "GUIDELINE_SUPERSEDED"
    APPRAISAL_VERSION_CHANGED = "APPRAISAL_VERSION_CHANGED"
    POLICY_VERSION_CHANGED = "POLICY_VERSION_CHANGED"
    CRITICAL_CONFLICT_CHANGED = "CRITICAL_CONFLICT_CHANGED"


@dataclass(frozen=True)
class GovernedEvidenceLifecycleEvent:
    event_id: str
    governed_evidence_id: str
    status: GovernedEvidenceLifecycleStatus
    triggers: tuple[ReevaluationTrigger, ...]
    occurred_at: datetime
    actor_id: str
    policy_version: str
    previous_event_hash: str | None
    event_hash: str


class GovernedEvidenceLifecycleRepository(Protocol):
    def append(self, event: GovernedEvidenceLifecycleEvent) -> None: ...
    def history(self, governed_evidence_id: str) -> tuple[GovernedEvidenceLifecycleEvent, ...]: ...


class GovernedEvidenceReevaluationService:
    def __init__(self, packages, lifecycle: GovernedEvidenceLifecycleRepository,
                 *, policy_version=None, appraisal_version=None, clock=None) -> None:
        self._packages, self._lifecycle = packages, lifecycle
        self._policy_version, self._appraisal_version = policy_version, appraisal_version
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def current_status(self, evidence: GovernedEvidence) -> str:
        history = self._lifecycle.history(evidence.governed_evidence_id)
        if history and history[-1].status != GovernedEvidenceLifecycleStatus.ACTIVE:
            return history[-1].status.value
        evaluation_time = self._clock()
        as_of = evaluation_time.date() if isinstance(evaluation_time, datetime) else evaluation_time
        return self.evaluate(evidence, as_of=as_of).status.value

    def evaluate(self, evidence: GovernedEvidence, *, as_of: date,
                 current_conflicts: tuple[str, ...] | None = None) -> GovernedEvidenceLifecycleEvent:
        triggers = []
        try:
            self._packages.get(evidence.evidence_package_id)
        except Exception:
            triggers.append(ReevaluationTrigger.PACKAGE_REVOKED)
        if evidence.guideline_expiration_date and as_of > date.fromisoformat(evidence.guideline_expiration_date):
            triggers.append(ReevaluationTrigger.GUIDELINE_EXPIRED)
        if evidence.guideline_withdrawn_at and as_of >= date.fromisoformat(evidence.guideline_withdrawn_at):
            triggers.append(ReevaluationTrigger.GUIDELINE_WITHDRAWN)
        if evidence.guideline_superseded_by:
            triggers.append(ReevaluationTrigger.GUIDELINE_SUPERSEDED)
        expected_appraisal = self._appraisal_version or evidence.appraisal_version
        expected_policy = self._policy_version or evidence.policy_version
        if evidence.appraisal_version != expected_appraisal:
            triggers.append(ReevaluationTrigger.APPRAISAL_VERSION_CHANGED)
        if evidence.policy_version != expected_policy:
            triggers.append(ReevaluationTrigger.POLICY_VERSION_CHANGED)
        if current_conflicts is not None and tuple(sorted(current_conflicts)) != tuple(sorted(evidence.conflict_status)):
            triggers.append(ReevaluationTrigger.CRITICAL_CONFLICT_CHANGED)
        status = GovernedEvidenceLifecycleStatus.ACTIVE
        if ReevaluationTrigger.PACKAGE_REVOKED in triggers:
            status = GovernedEvidenceLifecycleStatus.INVALIDATED
        elif triggers:
            status = GovernedEvidenceLifecycleStatus.REVIEW_REQUIRED
        history = self._lifecycle.history(evidence.governed_evidence_id)
        from .governed import _hash
        occurred_at, event_id = self._clock(), uuid4().hex
        previous_hash = history[-1].event_hash if history else None
        payload = {"event_id": event_id, "governed_evidence_id": evidence.governed_evidence_id,
            "status": status.value, "triggers": [item.value for item in triggers],
            "occurred_at": occurred_at.isoformat(), "actor_id": "reevaluation-policy",
            "policy_version": expected_policy, "previous_event_hash": previous_hash}
        event = GovernedEvidenceLifecycleEvent(event_id, evidence.governed_evidence_id, status,
            tuple(triggers), occurred_at, "reevaluation-policy", expected_policy,
            previous_hash, _hash(payload))
        self._lifecycle.append(event)
        return event
