"""Clinical intelligence domain and application boundary."""

from .governed import (
    CriticalConflictRequiresReview,
    GovernedClinicalIntelligenceService,
    GovernedClinicalRecommendation,
    GovernedEvidenceEligibilityGate,
    GovernedEvidenceRejected,
    GovernedRecommendationCandidate,
    HumanReviewStatus,
    ReviewTransitionRejected,
)
from .deprecated import DeprecatedClinicalPathError
from .governed_infrastructure import InMemoryGovernedDecisionAuditRepository
from .governance_infrastructure import (
    InMemoryConflictAdjudicationRepository,
    InMemoryGovernedEvidenceLifecycleRepository,
)
from .review_governance import (
    AuthorizedRecommendationReviewService,
    ConflictAdjudicationService,
    ConflictAdjudicationState,
    GovernedEvidenceLifecycleStatus,
    GovernedEvidenceReevaluationService,
    InMemoryReviewerAuthorizationAdapter,
    ReevaluationTrigger,
    ReviewAuthorizationPolicy,
    ReviewerIdentity,
    ReviewerRole,
    ReviewerStatus,
)
from .governance_persistence import PostgreSQLReviewerIdentityRepository

# ST-14 public boundary: the unqualified clinical service is governance-only.
ClinicalIntelligenceService = GovernedClinicalIntelligenceService

__all__ = [
    "ClinicalIntelligenceService", "DeprecatedClinicalPathError",
    "CriticalConflictRequiresReview", "GovernedClinicalIntelligenceService",
    "GovernedClinicalRecommendation", "GovernedEvidenceEligibilityGate",
    "GovernedEvidenceRejected", "GovernedRecommendationCandidate", "HumanReviewStatus",
    "InMemoryGovernedDecisionAuditRepository",
    "ReviewTransitionRejected",
    "AuthorizedRecommendationReviewService", "ConflictAdjudicationService",
    "ConflictAdjudicationState", "GovernedEvidenceLifecycleStatus",
    "GovernedEvidenceReevaluationService", "InMemoryConflictAdjudicationRepository",
    "InMemoryGovernedEvidenceLifecycleRepository", "InMemoryReviewerAuthorizationAdapter",
    "ReevaluationTrigger", "ReviewAuthorizationPolicy", "ReviewerIdentity", "ReviewerRole",
    "ReviewerStatus", "PostgreSQLReviewerIdentityRepository",
]
