from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Protocol
from uuid import uuid4

from jmoraIs.application import EvidencePackage, EvidencePackageQueryPort

from .domain import AppraisedRecommendation, AppraisalRequest, AppraisalRecordStatus, ClinicalAppraisalRecord
from .application import clinical_appraisal_integrity_hash


class GovernedEvidenceError(RuntimeError):
    pass


class GovernedEvidenceNotFound(GovernedEvidenceError):
    pass


class GovernedEvidenceIntegrityError(GovernedEvidenceError):
    pass


def governed_evidence_integrity_hash(evidence: "GovernedEvidence") -> str:
    payload = asdict(evidence); payload.pop("integrity_hash", None)
    for key in ("applicability", "conflict_status", "support_directions",
                "provenance_references", "ledger_references", "limitations"):
        payload[key] = list(payload[key])
    payload["issued_at"] = evidence.issued_at.isoformat()
    return _hash(payload)


def _hash(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class GovernedEvidence:
    governed_evidence_id: str
    evidence_package_id: str
    appraisal_result_id: str
    evidence_level: str
    methodological_quality: str
    methodological_quality_score: float
    recommendation_strength: str
    applicability: tuple[str, ...]
    guideline_authority: str
    guideline_governance_status: str
    guideline_expiration_date: str | None
    guideline_superseded_by: str | None
    guideline_withdrawn_at: str | None
    conflict_status: tuple[str, ...]
    support_directions: tuple[str, ...]
    provenance_references: tuple[str, ...]
    ledger_references: tuple[str, ...]
    policy_version: str
    appraisal_version: str
    limitations: tuple[str, ...]
    issued_at: datetime
    integrity_hash: str


class GovernedEvidenceRepository(Protocol):
    def append(self, evidence: GovernedEvidence) -> None: ...
    def get(self, governed_evidence_id: str) -> GovernedEvidence | None: ...
    def find_by_package_id(self, evidence_package_id: str) -> tuple[GovernedEvidence, ...]: ...
    def version_history(self, evidence_package_id: str) -> tuple[GovernedEvidence, ...]: ...


class GovernedEvidenceService:
    APPRAISAL_VERSION = "ST-13.1"

    def __init__(self, packages: EvidencePackageQueryPort, repository: GovernedEvidenceRepository, *, clock=None, appraisals=None) -> None:
        self._packages = packages
        self._repository = repository
        self._appraisals = appraisals
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def issue(self, appraisal: AppraisedRecommendation, request: AppraisalRequest) -> GovernedEvidence:
        """Legacy typed boundary; new compositions must use issue_persisted."""
        if not isinstance(appraisal, AppraisedRecommendation) or not isinstance(request, AppraisalRequest):
            raise GovernedEvidenceError("a typed appraisal result and request are required")
        return self._issue(appraisal, request, appraisal.recommendation_id)

    def _issue(
        self, appraisal: AppraisedRecommendation, request: AppraisalRequest,
        appraisal_result_id: str,
    ) -> GovernedEvidence:
        if not isinstance(appraisal, AppraisedRecommendation) or not isinstance(request, AppraisalRequest):
            raise GovernedEvidenceError("a typed appraisal result and request are required")
        if appraisal.recommendation_id != request.recommendation_id:
            raise GovernedEvidenceError("appraisal result does not match its request")
        try:
            package = self._packages.get(appraisal.evidence_package_id)
        except Exception as exc:
            raise GovernedEvidenceError("underlying EvidencePackage is invalid") from exc
        if not isinstance(package, EvidencePackage):
            raise GovernedEvidenceError("underlying package port returned an invalid type")

        issued_at = self._clock()
        identifier = uuid4().hex
        payload = {
            "governed_evidence_id": identifier,
            "evidence_package_id": appraisal.evidence_package_id,
            "appraisal_result_id": appraisal_result_id,
            "evidence_level": appraisal.explainability.evidence_level.name,
            "methodological_quality": appraisal.explainability.methodological_quality.value,
            "methodological_quality_score": appraisal.explainability.methodological_quality_score,
            "recommendation_strength": appraisal.explainability.recommendation_strength.name,
            "applicability": [item.value for item in appraisal.explainability.applicability],
            "guideline_authority": appraisal.explainability.guideline_authority,
            "guideline_governance_status": appraisal.recommendation_validity.value,
            "guideline_expiration_date": request.guideline.expiration_date.isoformat() if request.guideline.expiration_date else None,
            "guideline_superseded_by": request.guideline.superseded_by_guideline_id,
            "guideline_withdrawn_at": request.guideline.withdrawn_at.isoformat() if request.guideline.withdrawn_at else None,
            "conflict_status": [item.value for item in appraisal.explainability.conflicts_detected],
            "support_directions": sorted({item.support_direction.upper() for item in package.claim_evidence_relationships}),
            "provenance_references": list(appraisal.provenance_references),
            "ledger_references": list(appraisal.ledger_references),
            "policy_version": appraisal.policy_version,
            "appraisal_version": self.APPRAISAL_VERSION,
            "limitations": list(appraisal.explainability.limitations),
            "issued_at": issued_at.isoformat(),
        }
        evidence = GovernedEvidence(
            identifier, appraisal.evidence_package_id, appraisal_result_id,
            payload["evidence_level"], payload["methodological_quality"],
            payload["methodological_quality_score"], payload["recommendation_strength"],
            tuple(payload["applicability"]), payload["guideline_authority"],
            payload["guideline_governance_status"], payload["guideline_expiration_date"],
            payload["guideline_superseded_by"], payload["guideline_withdrawn_at"],
            tuple(payload["conflict_status"]),
            tuple(payload["support_directions"]), tuple(payload["provenance_references"]),
            tuple(payload["ledger_references"]), appraisal.policy_version,
            self.APPRAISAL_VERSION, tuple(payload["limitations"]), issued_at, _hash(payload),
        )
        self._repository.append(evidence)
        return evidence

    def issue_persisted(self, appraisal_id: str) -> GovernedEvidence:
        if self._appraisals is None:
            raise GovernedEvidenceError("canonical appraisal query port is required")
        record = self._appraisals.get(appraisal_id)
        if not isinstance(record, ClinicalAppraisalRecord):
            raise GovernedEvidenceError("persisted appraisal type is invalid")
        if record.status is not AppraisalRecordStatus.ELIGIBLE:
            raise GovernedEvidenceError("persisted appraisal is not eligible")
        if record.framework_version != self.APPRAISAL_VERSION:
            raise GovernedEvidenceError("persisted appraisal framework version is unsupported")
        if record.integrity_hash != clinical_appraisal_integrity_hash(record):
            raise GovernedEvidenceError("persisted appraisal integrity verification failed")
        if not record.provenance_references or record.evidence_package_id != record.appraisal.evidence_package_id:
            raise GovernedEvidenceError("persisted appraisal trust linkage is invalid")
        return self._issue(record.appraisal, record.source_request, record.appraisal_id)

    def get(self, governed_evidence_id: str) -> GovernedEvidence:
        if not isinstance(governed_evidence_id, str):
            raise GovernedEvidenceError("governed evidence identifier must be a string")
        evidence = self._repository.get(governed_evidence_id)
        if evidence is None:
            raise GovernedEvidenceNotFound("governed evidence does not exist")
        if evidence.integrity_hash != governed_evidence_integrity_hash(evidence):
            raise GovernedEvidenceIntegrityError("governed evidence integrity check failed")
        self._packages.get(evidence.evidence_package_id)
        return evidence
