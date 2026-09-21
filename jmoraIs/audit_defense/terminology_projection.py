from __future__ import annotations

from jmoraIs.terminology.domain import (
    ClinicalConcept,
    GovernedTerminologyReference,
    MappingConfidence,
    MappingReviewStatus,
    MappingType,
    TerminologyStatus,
)
from jmoraIs.terminology.governance import mapping_governance_integrity_hash

from .domain import AuditDefenseBoundaryRejected


class PostgreSQLGovernedAuditTerminologyAdapter:
    """Restart-safe projection over canonical terminology and mapping governance."""

    def __init__(self, concepts, governance, *, policy_version: str):
        self._concepts = concepts
        self._governance = governance
        self._policy_version = policy_version

    def get_governed(self, concept_id: str) -> GovernedTerminologyReference:
        if not isinstance(concept_id, str) or not concept_id.strip():
            raise AuditDefenseBoundaryRejected("canonical terminology concept ID is required")
        concept = self._concepts.latest(concept_id)
        if not isinstance(concept, ClinicalConcept) or concept.canonical_id != concept_id:
            raise AuditDefenseBoundaryRejected("persisted ClinicalConcept is required")
        record = self._governance.current_by_concept(concept_id)
        if record is None:
            raise AuditDefenseBoundaryRejected("persisted terminology mapping governance is required")
        if record.integrity_hash != mapping_governance_integrity_hash(record):
            raise AuditDefenseBoundaryRejected("terminology mapping governance integrity is invalid")
        if record.target_concept_id != concept.canonical_id or record.terminology_version != concept.version:
            raise AuditDefenseBoundaryRejected("concept and mapping governance linkage is invalid")
        if record.policy_version != self._policy_version or not record.provenance_references:
            raise AuditDefenseBoundaryRejected("terminology mapping policy or provenance is invalid")
        history = self._governance.history_by_concept(concept_id)
        previous = None
        for position, item in enumerate(history, 1):
            if (item.version != position
                    or item.predecessor_record_id != (previous.governance_record_id if previous else None)
                    or item.integrity_hash != mapping_governance_integrity_hash(item)):
                raise AuditDefenseBoundaryRejected("terminology mapping governance history is invalid")
            previous = item
        if not history or history[-1] != record:
            raise AuditDefenseBoundaryRejected("terminology mapping governance history is incomplete")
        return GovernedTerminologyReference(
            concept=concept,
            governance_record_id=record.governance_record_id,
            mapping_type=record.mapping_type,
            mapping_confidence=record.mapping_confidence,
            review_status=record.review_status,
            review_required=record.review_required,
            policy_version=record.policy_version,
            provenance_references=record.provenance_references,
            mapping_method=record.mapping_method,
            governance_version=record.version,
            created_at=record.created_at,
        )

    def get(self, concept_id: str) -> ClinicalConcept:
        governed = self.get_governed(concept_id)
        if (governed.concept.status is not TerminologyStatus.ACTIVE
                or governed.mapping_type not in {MappingType.EXACT, MappingType.EQUIVALENT}
                or governed.mapping_confidence not in {MappingConfidence.HIGH, MappingConfidence.MEDIUM}
                or governed.review_required
                or governed.review_status in {MappingReviewStatus.REVIEW_REQUIRED, MappingReviewStatus.REJECTED}):
            raise AuditDefenseBoundaryRejected("governed terminology mapping is not eligible")
        return governed.concept
