from __future__ import annotations

from jmoraIs.appraisal.application import clinical_appraisal_integrity_hash
from jmoraIs.appraisal.domain import AppraisalRecordStatus, ClinicalAppraisalRecord
from jmoraIs.appraisal.governed import GovernedEvidence

from .domain import AuditDefenseBoundaryRejected


class CanonicalGovernedAuditEvidenceAdapter:
    """Restart-safe governed-evidence read boundary composed from canonical services."""

    def __init__(self, governed_evidence_query, lifecycle, appraisal_query):
        self._governed_evidence_query = governed_evidence_query
        self._lifecycle = lifecycle
        self._appraisal_query = appraisal_query

    def get(self, governed_evidence_id):
        if not isinstance(governed_evidence_id, str) or not governed_evidence_id.strip():
            raise AuditDefenseBoundaryRejected("opaque GovernedEvidence identifier is required")
        try:
            evidence = self._governed_evidence_query.get(governed_evidence_id)
        except Exception as exc:
            raise AuditDefenseBoundaryRejected("canonical GovernedEvidence resolution failed") from exc
        if not isinstance(evidence, GovernedEvidence) or evidence.governed_evidence_id != governed_evidence_id:
            raise AuditDefenseBoundaryRejected("canonical GovernedEvidence identity is invalid")
        self._validate_linkage(evidence)
        try:
            lifecycle = self._lifecycle.current_status(evidence)
        except Exception as exc:
            raise AuditDefenseBoundaryRejected("GovernedEvidence lifecycle validation failed") from exc
        if lifecycle != "ACTIVE":
            raise AuditDefenseBoundaryRejected(f"GovernedEvidence is not active: {lifecycle}")
        return evidence

    def _validate_linkage(self, evidence):
        required = (
            evidence.evidence_package_id, evidence.appraisal_result_id, evidence.evidence_level,
            evidence.methodological_quality, evidence.recommendation_strength,
            evidence.policy_version, evidence.appraisal_version,
        )
        if not all(required) or not evidence.provenance_references or not evidence.ledger_references:
            raise AuditDefenseBoundaryRejected("GovernedEvidence trust linkage is incomplete")
        try:
            appraisal = self._appraisal_query.get(evidence.appraisal_result_id)
        except Exception as exc:
            raise AuditDefenseBoundaryRejected("canonical appraisal resolution failed") from exc
        if not isinstance(appraisal, ClinicalAppraisalRecord):
            raise AuditDefenseBoundaryRejected("canonical appraisal type is invalid")
        if appraisal.integrity_hash != clinical_appraisal_integrity_hash(appraisal):
            raise AuditDefenseBoundaryRejected("canonical appraisal integrity is invalid")
        if appraisal.status is not AppraisalRecordStatus.ELIGIBLE:
            raise AuditDefenseBoundaryRejected("canonical appraisal is not eligible")
        if (appraisal.appraisal_id != evidence.appraisal_result_id
                or appraisal.evidence_package_id != evidence.evidence_package_id
                or appraisal.framework_version != evidence.appraisal_version
                or appraisal.policy_version != evidence.policy_version
                or not appraisal.provenance_references):
            raise AuditDefenseBoundaryRejected("GovernedEvidence appraisal linkage is invalid")
