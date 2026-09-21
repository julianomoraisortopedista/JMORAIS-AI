from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Protocol
from uuid import uuid4

from jmoraIs.appraisal.governed import GovernedEvidence
from jmoraIs.appraisal.exact_reference import PersistedGovernedEvidenceReference


class GovernedClinicalError(RuntimeError):
    pass


class GovernedEvidenceRejected(GovernedClinicalError):
    pass


class CriticalConflictRequiresReview(GovernedEvidenceRejected):
    pass


class ReviewTransitionRejected(GovernedClinicalError):
    pass


class HumanReviewStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED_BY_REVIEWER = "APPROVED_BY_REVIEWER"
    REJECTED_BY_REVIEWER = "REJECTED_BY_REVIEWER"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"


class GovernedEvidenceQueryPort(Protocol):
    def get(self, governed_evidence_id: str) -> GovernedEvidence: ...

class GovernedEvidenceExactReferenceQueryPort(Protocol):
    def get_exact(self,reference:PersistedGovernedEvidenceReference)->GovernedEvidence:...


class GovernedDecisionAuditPort(Protocol):
    def append(self, event: "GovernedDecisionAuditEvent") -> None: ...
    def history(self, case_id: str) -> tuple["GovernedDecisionAuditEvent", ...]: ...


class GovernedEvidenceLifecycleEligibilityPort(Protocol):
    def current_status(self, evidence: GovernedEvidence) -> str: ...


@dataclass(frozen=True)
class GovernedRecommendationCandidate:
    candidate_id: str
    recommendation: str
    governed_evidence_ids: tuple[str, ...]
    required_applicability: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.candidate_id.strip() or not self.recommendation.strip() or not self.governed_evidence_ids:
            raise ValueError("candidate and governed evidence are required")
        if not all(isinstance(identifier, str) and identifier.strip() for identifier in self.governed_evidence_ids):
            raise ValueError("governed evidence identifiers must be opaque strings")
        if len(self.governed_evidence_ids) != len(set(self.governed_evidence_ids)):
            raise ValueError("governed evidence cannot be counted twice")
        if not self.required_applicability:
            raise ValueError("required applicability is required")


@dataclass(frozen=True)
class GovernedRecommendationExplanation:
    scientific_evidence_sources: tuple[str, ...]
    appraisal_quality: tuple[str, ...]
    evidence_hierarchy: tuple[str, ...]
    guideline_authorities: tuple[str, ...]
    recommendation_strengths: tuple[str, ...]
    applicability: tuple[str, ...]
    conflicts: tuple[str, ...]
    limitations: tuple[str, ...]
    confidence_contributors: tuple[str, ...]
    supporting_weight: float
    opposing_weight: float
    neutral_weight: float
    inconclusive_weight: float
    human_review_status: HumanReviewStatus


@dataclass(frozen=True)
class GovernedClinicalRecommendation:
    recommendation_id: str
    candidate_id: str
    recommendation: str
    rank: int
    ranking_score: float
    confidence_score: float
    governed_evidence_ids: tuple[str, ...]
    evidence_package_ids: tuple[str, ...]
    provenance_references: tuple[str, ...]
    ledger_references: tuple[str, ...]
    policy_versions: tuple[str, ...]
    explanation: GovernedRecommendationExplanation
    review_status: HumanReviewStatus
    externally_actionable: bool


@dataclass(frozen=True)
class GovernedDecisionAuditEvent:
    event_id: str
    case_id: str
    event_type: str
    occurred_at: datetime
    governed_evidence_ids: tuple[str, ...]
    recommendation_ids: tuple[str, ...]
    weighting_decisions: tuple[str, ...]
    conflict_decisions: tuple[str, ...]
    confidence_inputs: tuple[str, ...]
    review_from: str | None
    review_to: str | None
    reviewer_id: str | None
    actor_role: str | None
    policy_version: str
    justification: str | None
    previous_event_hash: str | None
    event_hash: str


class GovernedEvidenceEligibilityGate:
    CRITICAL_CONFLICTS = {"CONFLICTING_RECOMMENDATIONS", "CONFLICTING_ORGANIZATIONS"}

    def __init__(self, lifecycle: GovernedEvidenceLifecycleEligibilityPort) -> None:
        self._lifecycle = lifecycle

    def evaluate(self, evidence: GovernedEvidence, required_applicability: tuple[str, ...]) -> None:
        if not isinstance(evidence, GovernedEvidence):
            raise GovernedEvidenceRejected("only GovernedEvidence is accepted")
        required = (
            evidence.evidence_package_id, evidence.appraisal_result_id, evidence.evidence_level,
            evidence.methodological_quality, evidence.recommendation_strength,
            evidence.guideline_authority, evidence.policy_version, evidence.appraisal_version,
        )
        if not all(value for value in required) or not evidence.provenance_references or not evidence.ledger_references:
            raise GovernedEvidenceRejected("governance or trust linkage is incomplete")
        if evidence.guideline_governance_status != "VALID":
            raise GovernedEvidenceRejected(f"ineligible governance: {evidence.guideline_governance_status}")
        lifecycle = self._lifecycle.current_status(evidence)
        if lifecycle != "ACTIVE":
            raise GovernedEvidenceRejected(f"ineligible governed evidence lifecycle: {lifecycle}")
        critical = self.CRITICAL_CONFLICTS.intersection(evidence.conflict_status)
        if critical:
            raise CriticalConflictRequiresReview("critical conflict requires explicit human resolution")
        if not set(required_applicability).issubset(evidence.applicability):
            raise GovernedEvidenceRejected("governed evidence applicability is incompatible")


class GovernedClinicalIntelligenceService:
    METHODOLOGY_VERSION = "ST-14.1"
    _LEVEL = {
        "SYSTEMATIC_REVIEW": 1.0, "META_ANALYSIS": .95,
        "RANDOMIZED_CONTROLLED_TRIAL": .9, "COHORT": .7, "CASE_CONTROL": .6,
        "CROSS_SECTIONAL": .5, "CASE_SERIES": .35, "CASE_REPORT": .25,
        "EXPERT_OPINION": .15,
    }
    _STRENGTH = {"STRONG_FOR": 1.0, "CONDITIONAL_FOR": .75, "NEUTRAL": .5,
                 "CONDITIONAL_AGAINST": .75, "STRONG_AGAINST": 1.0}

    def __init__(self, governed: GovernedEvidenceQueryPort, audit: GovernedDecisionAuditPort,
                 gate: GovernedEvidenceEligibilityGate, *, clock=None) -> None:
        self._governed = governed
        self._audit = audit
        self._gate = gate
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def evaluate(self, *, case_id: str, candidates: tuple[GovernedRecommendationCandidate, ...]):
        if not case_id.strip() or not candidates:
            raise ValueError("case_id and candidates are required")
        resolved: dict[str, GovernedEvidence] = {}
        for candidate in candidates:
            for identifier in candidate.governed_evidence_ids:
                if not isinstance(identifier, str):
                    raise GovernedEvidenceRejected("arbitrary evidence objects are rejected")
                try:
                    evidence = self._governed.get(identifier)
                except CriticalConflictRequiresReview:
                    raise
                except Exception as exc:
                    raise GovernedEvidenceRejected(f"governed evidence rejected: {identifier}") from exc
                try:
                    self._gate.evaluate(evidence, candidate.required_applicability)
                except CriticalConflictRequiresReview:
                    self._audit.append(self._blocked_event(case_id, evidence))
                    raise
                resolved[identifier] = evidence
        recommendations = [self._recommend(item, resolved) for item in candidates]
        recommendations.sort(key=lambda item: (-item.ranking_score, item.candidate_id))
        ranked = tuple(replace(item, rank=index) for index, item in enumerate(recommendations, 1))
        event = self._decision_event(case_id, ranked)
        self._audit.append(event)
        return ranked

    def _recommend(self, candidate, resolved):
        weights = {key: 0.0 for key in ("SUPPORTING", "OPPOSING", "NEUTRAL", "INCONCLUSIVE")}
        evidence = tuple(resolved[item] for item in candidate.governed_evidence_ids)
        decisions = []
        for item in evidence:
            weight = self._LEVEL[item.evidence_level] * item.methodological_quality_score * self._STRENGTH[item.recommendation_strength]
            directions = item.support_directions or ("INCONCLUSIVE",)
            for direction in directions:
                weights[direction if direction in weights else "INCONCLUSIVE"] += weight / len(directions)
            decisions.append(f"{item.governed_evidence_id}: hierarchy*quality*strength={weight:.4f}")
        decisive = weights["SUPPORTING"] + weights["OPPOSING"]
        conflict = min(weights["SUPPORTING"], weights["OPPOSING"]) / max(weights["SUPPORTING"], weights["OPPOSING"]) if max(weights["SUPPORTING"], weights["OPPOSING"]) else 0.0
        sufficiency = min(decisive / 1.5, 1.0)
        confidence = round((abs(weights["SUPPORTING"] - weights["OPPOSING"]) / decisive if decisive else 0.0) * sufficiency, 4)
        ranking = round((weights["SUPPORTING"] / decisive if decisive else 0.0) * sufficiency * (1 - .5 * conflict), 4)
        conflicts = tuple(sorted({value for item in evidence for value in item.conflict_status}))
        limitations = tuple(dict.fromkeys(value for item in evidence for value in item.limitations))
        explanation = GovernedRecommendationExplanation(
            tuple(sorted({value for item in evidence for value in item.provenance_references})),
            tuple(item.methodological_quality for item in evidence),
            tuple(item.evidence_level for item in evidence),
            tuple(item.guideline_authority for item in evidence),
            tuple(item.recommendation_strength for item in evidence),
            tuple(sorted({value for item in evidence for value in item.applicability})),
            conflicts, limitations, tuple(decisions),
            *(round(weights[key], 4) for key in ("SUPPORTING", "OPPOSING", "NEUTRAL", "INCONCLUSIVE")),
            HumanReviewStatus.PENDING_REVIEW,
        )
        recommendation_id = _hash({"candidate": candidate.candidate_id,
                                   "governed": list(candidate.governed_evidence_ids),
                                   "methodology": self.METHODOLOGY_VERSION})
        return GovernedClinicalRecommendation(
            recommendation_id, candidate.candidate_id, candidate.recommendation, 0, ranking,
            confidence, candidate.governed_evidence_ids,
            tuple(sorted({item.evidence_package_id for item in evidence})),
            tuple(sorted({value for item in evidence for value in item.provenance_references})),
            tuple(sorted({value for item in evidence for value in item.ledger_references})),
            tuple(sorted({item.policy_version for item in evidence})), explanation,
            HumanReviewStatus.PENDING_REVIEW, False,
        )

    def _decision_event(self, case_id, recommendations):
        history = self._audit.history(case_id)
        return _event(
            case_id, "GOVERNED_RECOMMENDATIONS_RANKED", self._clock(),
            tuple(sorted({value for item in recommendations for value in item.governed_evidence_ids})),
            tuple(item.recommendation_id for item in recommendations),
            tuple(value for item in recommendations for value in item.explanation.confidence_contributors),
            tuple(value for item in recommendations for value in item.explanation.conflicts),
            tuple(f"{item.recommendation_id}: confidence={item.confidence_score:.4f}" for item in recommendations),
            None, HumanReviewStatus.PENDING_REVIEW.value, None, None, self.METHODOLOGY_VERSION, None,
            history[-1].event_hash if history else None,
        )

    def _blocked_event(self, case_id: str, evidence: GovernedEvidence) -> GovernedDecisionAuditEvent:
        history = self._audit.history(case_id)
        return _event(
            case_id, "CRITICAL_CONFLICT_BLOCKED", self._clock(),
            (evidence.governed_evidence_id,), (), (), tuple(evidence.conflict_status), (),
            None, HumanReviewStatus.PENDING_REVIEW.value, None, None, self.METHODOLOGY_VERSION,
            "Critical conflict blocked automatically.",
            history[-1].event_hash if history else None,
        )


class RecommendationReviewService:
    """Deprecated unauthenticated review path; retained only as a fail-closed tombstone."""

    def __init__(self, *args, **kwargs) -> None:
        from .deprecated import DeprecatedClinicalPathError
        raise DeprecatedClinicalPathError(
            "review without authorization is blocked; use AuthorizedRecommendationReviewService"
        )


def _hash(payload: object) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _event(case_id, event_type, occurred_at, governed_ids, recommendation_ids, weighting,
           conflicts, confidence, review_from, review_to, reviewer_id, actor_role,
           policy_version, justification, previous_hash):
    event_id = uuid4().hex
    payload = {"event_id": event_id, "case_id": case_id, "event_type": event_type,
               "occurred_at": occurred_at.isoformat(), "governed_evidence_ids": list(governed_ids),
               "recommendation_ids": list(recommendation_ids), "weighting": list(weighting),
               "conflicts": list(conflicts), "confidence": list(confidence),
               "review_from": review_from, "review_to": review_to, "reviewer_id": reviewer_id,
               "actor_role": actor_role, "policy_version": policy_version,
               "justification": justification,
               "previous_event_hash": previous_hash}
    return GovernedDecisionAuditEvent(event_id, case_id, event_type, occurred_at, governed_ids,
        recommendation_ids, weighting, conflicts, confidence, review_from, review_to, reviewer_id,
        actor_role, policy_version, justification,
        previous_hash, _hash(payload))
