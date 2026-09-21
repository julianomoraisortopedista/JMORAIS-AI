from __future__ import annotations

from datetime import date, datetime, timezone
from dataclasses import asdict
from enum import Enum
from hashlib import sha256
import json
from jmoraIs.application import EvidencePackage, EvidencePackageQueryPort

from .domain import (
    AppraisalRequest,
    AppraisedRecommendation,
    ConflictType,
    GuidelineConflictResolution,
    GuidelineConflictResolver,
    GuidelineStatus,
    RecommendationExplainability,
    RecommendationValidity,
    ClinicalAppraisalRecord, AppraisalRecordStatus,
)


class AppraisalEvidenceRejected(RuntimeError):
    pass


def clinical_appraisal_integrity_hash(record: ClinicalAppraisalRecord) -> str:
    payload = asdict(record)
    payload.pop("integrity_hash", None)

    def encode(value):
        if isinstance(value, Enum):
            return value.value
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        raise TypeError(type(value).__name__)

    canonical = json.dumps(payload, default=encode, sort_keys=True, separators=(",", ":"))
    return sha256(canonical.encode("utf-8")).hexdigest()


class ClinicalAppraisalService:
    """Validates scientific packages before producing governed clinical appraisals."""

    def __init__(self, packages: EvidencePackageQueryPort, resolver: GuidelineConflictResolver | None = None) -> None:
        self._packages = packages
        self._resolver = resolver or GuidelineConflictResolver()

    def assess(
        self, requests: tuple[AppraisalRequest, ...], *, as_of: date,
    ) -> tuple[tuple[AppraisedRecommendation, ...], GuidelineConflictResolution]:
        if not requests:
            raise ValueError("appraisal requests are required")
        if len({item.recommendation_id for item in requests}) != len(requests):
            raise ValueError("recommendation identifiers must be unique")

        packages: dict[str, EvidencePackage] = {}
        for request in requests:
            try:
                package = self._packages.get(request.evidence_package_id)
            except Exception as exc:
                raise AppraisalEvidenceRejected(
                    f"EvidencePackage rejected: {request.evidence_package_id}"
                ) from exc
            if not isinstance(package, EvidencePackage):
                raise AppraisalEvidenceRejected("validated port returned an invalid package type")
            if not package.provenance_references or not package.ledger_references:
                raise AppraisalEvidenceRejected("EvidencePackage lacks mandatory trust linkage")
            packages[request.evidence_package_id] = package

        resolution = self._resolver.resolve(requests, as_of)
        conflict_map: dict[str, set[ConflictType]] = {}
        for conflict in resolution.conflicts:
            for recommendation_id in conflict.recommendation_ids:
                conflict_map.setdefault(recommendation_id, set()).add(conflict.conflict_type)

        appraised = tuple(
            self._appraise(request, packages[request.evidence_package_id], as_of,
                           tuple(sorted(conflict_map.get(request.recommendation_id, set()), key=lambda item: item.value)))
            for request in requests
        )
        return appraised, resolution

    @staticmethod
    def _appraise(request, package, as_of, conflicts):
        status = request.guideline.status(as_of)
        validity = {
            GuidelineStatus.ACTIVE: RecommendationValidity.VALID,
            GuidelineStatus.EXPIRED: RecommendationValidity.EXPIRED_GUIDELINE,
            GuidelineStatus.SUPERSEDED: RecommendationValidity.SUPERSEDED_RECOMMENDATION,
            GuidelineStatus.WITHDRAWN: RecommendationValidity.WITHDRAWN_RECOMMENDATION,
        }[status]
        limitations = list(request.methodological_quality.limitations + request.limitations)
        if validity != RecommendationValidity.VALID:
            limitations.append(f"Recommendation is not current: {validity.value}.")
        if conflicts:
            limitations.append("Guideline conflicts require explicit human resolution.")
        explanation = RecommendationExplainability(
            request.evidence_level, request.methodological_quality.quality,
            request.methodological_quality.score, request.recommendation_strength,
            request.guideline.issuing_organization, conflicts, request.applicability,
            tuple(dict.fromkeys(limitations)),
        )
        return AppraisedRecommendation(
            request.recommendation_id, request.topic_id, request.recommendation,
            request.evidence_package_id, validity,
            validity == RecommendationValidity.VALID and not conflicts,
            explanation, tuple(package.provenance_references), tuple(package.ledger_references),
            package.policy_version,
        )

class ClinicalAppraisalPersistenceService:
    FRAMEWORK="JMORAIS-CLINICAL-APPRAISAL"; FRAMEWORK_VERSION="ST-13.1"
    def __init__(self,decision:ClinicalAppraisalService,repository,*,clock=None):
        self._decision,self._repository=decision,repository
        self._clock=clock or (lambda:datetime.now(timezone.utc))
    def assess_and_persist(self,requests,*,as_of,reviewer_reference=None,reviewer_status="NOT_REVIEWED"):
        results,resolution=self._decision.assess(requests,as_of=as_of);records=[]
        for appraisal,request in zip(results,requests):
            previous=self._repository.current(request.recommendation_id);version=1 if previous is None else previous.appraisal_version+1
            created=self._clock();identity=sha256(f"{request.recommendation_id}|{version}|{appraisal.evidence_package_id}".encode()).hexdigest()
            status=AppraisalRecordStatus.ELIGIBLE if appraisal.eligible_for_clinical_intelligence else AppraisalRecordStatus.REVIEW_REQUIRED
            unsigned_record=ClinicalAppraisalRecord(identity,appraisal.evidence_package_id,request.recommendation_id,self.FRAMEWORK,
                self.FRAMEWORK_VERSION,version,previous.appraisal_id if previous else None,status,appraisal,request,
                appraisal.provenance_references,reviewer_reference,reviewer_status,appraisal.policy_version,created,None,"pending")
            record = ClinicalAppraisalRecord(
                **{**unsigned_record.__dict__, "integrity_hash": clinical_appraisal_integrity_hash(unsigned_record)}
            )
            self._repository.append(record);records.append(record)
        return tuple(records),resolution
    def get(self,appraisal_id):
        value=self._repository.get(appraisal_id)
        if value is None:raise AppraisalEvidenceRejected("persisted appraisal does not exist")
        if value.integrity_hash != clinical_appraisal_integrity_hash(value):
            raise AppraisalEvidenceRejected("persisted appraisal integrity verification failed")
        return value
