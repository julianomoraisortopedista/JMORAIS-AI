"""Projections of exact owner reads, never new clinical decisions.

Integrity status denotes a successful owner exact reread, not clinical approval.
The explainability projection is limited to recorded input-quality explanations
and exact upstream lineage, not a generated reasoning narrative.
"""
from dataclasses import dataclass
from datetime import datetime

from jmoraIs.appraisal.exact_reference import PersistedGovernedEvidenceReference
from jmoraIs.appraisal.governed import GovernedEvidence
from jmoraIs.clinical.governed import GovernedEvidenceExactReferenceQueryPort
from jmoraIs.clinical_state.domain import PatientClinicalState
from jmoraIs.clinical_state.exact_reference import PersistedClinicalStateReference
from jmoraIs.clinical_state.ports import ClinicalStateExactReferenceQueryPort
from jmoraIs.reasoning_input.domain import ClinicalReasoningInput
from jmoraIs.reasoning_input.exact_reference import PersistedClinicalReasoningInputReference
from jmoraIs.tenancy.context import current_tenant_context


class WorkspaceReadRejected(RuntimeError):
    """No partial view or fallback is returned after a rejected source read."""


@dataclass(frozen=True)
class ClinicalSummaryView:
    source_reference: PersistedClinicalStateReference
    pseudonymous_patient_id: str
    state_version: int
    as_of: datetime
    review_status: str
    quality_flags: tuple[str, ...]
    provenance_references: tuple[str, ...]
    integrity_status: str = "OWNER_EXACT_REREAD"


@dataclass(frozen=True)
class EvidenceView:
    source_reference: PersistedGovernedEvidenceReference
    evidence_level: str
    methodological_quality: str
    recommendation_strength: str
    guideline_governance_status: str
    applicability: tuple[str, ...]
    support_directions: tuple[str, ...]
    conflict_status: tuple[str, ...]
    limitations: tuple[str, ...]
    provenance_references: tuple[str, ...]
    ledger_references: tuple[str, ...]
    integrity_status: str = "OWNER_EXACT_REREAD"


@dataclass(frozen=True)
class ExplainabilityView:
    # This approved reference retains exact State/Evidence/Terminology lineage.
    source_reference: PersistedClinicalReasoningInputReference
    review_status: str
    readiness: str
    missing_data_references: tuple[str, ...]
    conflicting_data_references: tuple[str, ...]
    stale_data_references: tuple[str, ...]
    review_required: bool
    integrity_status: str = "OWNER_EXACT_REREAD"


@dataclass(frozen=True)
class ClinicalWorkspaceView:
    tenant_id: str
    clinical_summary: ClinicalSummaryView
    evidence: tuple[EvidenceView, ...]
    explainability: ExplainabilityView


def _require_reference(reference, expected_type):
    tenant = current_tenant_context()
    if not isinstance(reference, expected_type) or reference.tenant_id != tenant.tenant_id:
        raise WorkspaceReadRejected("tenant-bound persisted exact reference is required")


class ClinicalWorkspace:
    def __init__(self, clinical_states: ClinicalStateExactReferenceQueryPort,
                 governed_evidence: GovernedEvidenceExactReferenceQueryPort, reasoning_inputs):
        # reasoning_inputs is the existing owner get_exact(reference) operation;
        # no new reference authority, persistence adapter or issuance API here.
        self._states = clinical_states
        self._evidence = governed_evidence
        self._reasoning = reasoning_inputs

    def clinical_summary(self, reference: PersistedClinicalStateReference) -> ClinicalSummaryView:
        _require_reference(reference, PersistedClinicalStateReference)
        value = self._states.get_exact(reference)
        if not isinstance(value, PatientClinicalState):
            raise WorkspaceReadRejected("exact Clinical State is unavailable")
        return ClinicalSummaryView(reference, value.pseudonymous_patient_id, value.state_version,
                                   value.as_of, value.review_status.value,
                                   tuple(flag.flag_type.value for flag in value.quality_flags),
                                   value.provenance_references)

    def evidence(self, reference: PersistedGovernedEvidenceReference) -> EvidenceView:
        _require_reference(reference, PersistedGovernedEvidenceReference)
        value = self._evidence.get_exact(reference)
        if not isinstance(value, GovernedEvidence):
            raise WorkspaceReadRejected("exact Governed Evidence is unavailable")
        return EvidenceView(reference, value.evidence_level, value.methodological_quality,
                            value.recommendation_strength, value.guideline_governance_status,
                            value.applicability, value.support_directions, value.conflict_status,
                            value.limitations, value.provenance_references, value.ledger_references)

    def explainability(self, reference: PersistedClinicalReasoningInputReference) -> ExplainabilityView:
        _require_reference(reference, PersistedClinicalReasoningInputReference)
        value = self._reasoning.get_exact(reference)
        if not isinstance(value, ClinicalReasoningInput):
            raise WorkspaceReadRejected("exact Clinical Reasoning Input is unavailable")
        # Composition consistency only; authentication stays with the owners.
        if (value.clinical_state_reference, value.governed_evidence_references,
            value.terminology_governance_references) != (
                reference.clinical_state_reference, reference.governed_evidence_references,
                reference.terminology_governance_references):
            raise WorkspaceReadRejected("exact upstream lineage mismatch")
        return ExplainabilityView(reference, value.review_status.value, value.readiness.value,
                                  value.quality.missing_data_references,
                                  value.quality.conflicting_data_references,
                                  value.quality.stale_data_references, value.quality.review_required)

    def read(self, reference: PersistedClinicalReasoningInputReference) -> ClinicalWorkspaceView:
        explanation = self.explainability(reference)
        summary = self.clinical_summary(reference.clinical_state_reference)
        if summary.pseudonymous_patient_id != reference.subject_reference:
            raise WorkspaceReadRejected("workspace patient lineage mismatch")
        evidence = tuple(self.evidence(item) for item in reference.governed_evidence_references)
        return ClinicalWorkspaceView(reference.tenant_id, summary, evidence, explanation)
