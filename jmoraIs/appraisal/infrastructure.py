from __future__ import annotations

from .governed import GovernedEvidence, GovernedEvidenceError
from .domain import AppraisalInvariantError, ClinicalAppraisalRecord


class InMemoryGovernedEvidenceRepository:
    """Append-only reference adapter for the governed boundary catalog."""

    def __init__(self) -> None:
        self._items: dict[str, GovernedEvidence] = {}

    def append(self, evidence: GovernedEvidence) -> None:
        if evidence.governed_evidence_id in self._items:
            raise GovernedEvidenceError("governed evidence cannot be overwritten")
        self._items[evidence.governed_evidence_id] = evidence

    def get(self, governed_evidence_id: str) -> GovernedEvidence | None:
        return self._items.get(governed_evidence_id)

    def find_by_package_id(self, evidence_package_id: str) -> tuple[GovernedEvidence, ...]:
        return tuple(item for item in self._items.values() if item.evidence_package_id == evidence_package_id)

    def version_history(self, evidence_package_id: str) -> tuple[GovernedEvidence, ...]:
        return self.find_by_package_id(evidence_package_id)


class InMemoryClinicalAppraisalRepository:
    """Append-only development adapter for canonical appraisal records."""

    def __init__(self) -> None:
        self._items: dict[str, ClinicalAppraisalRecord] = {}

    def append(self, record: ClinicalAppraisalRecord) -> None:
        if record.appraisal_id in self._items:
            raise AppraisalInvariantError("clinical appraisal cannot be overwritten")
        previous = self.current(record.recommendation_reference)
        expected_version = 1 if previous is None else previous.appraisal_version + 1
        expected_predecessor = None if previous is None else previous.appraisal_id
        if record.appraisal_version != expected_version or record.predecessor_appraisal_id != expected_predecessor:
            raise AppraisalInvariantError("invalid appraisal predecessor")
        self._items[record.appraisal_id] = record

    def get(self, appraisal_id: str) -> ClinicalAppraisalRecord | None:
        return self._items.get(appraisal_id)

    def current(self, recommendation_reference: str) -> ClinicalAppraisalRecord | None:
        history = self.history(recommendation_reference)
        return history[-1] if history else None

    def history(self, recommendation_reference: str) -> tuple[ClinicalAppraisalRecord, ...]:
        return tuple(sorted(
            (item for item in self._items.values() if item.recommendation_reference == recommendation_reference),
            key=lambda item: item.appraisal_version,
        ))

    def by_evidence_package(self, evidence_package_id: str) -> tuple[ClinicalAppraisalRecord, ...]:
        return tuple(item for item in self._items.values() if item.evidence_package_id == evidence_package_id)
