"""Exact historical metadata only; no clinical actions or inferred current state."""
from dataclasses import dataclass
from datetime import datetime

from jmoraIs.audit_defense.domain import DefensePackage, DefenseReferenceState, PersistedDefensePackageReference
from jmoraIs.audit_defense.ports import AuditDefenseQueryPort
from jmoraIs.clinical_state.exact_reference import PersistedClinicalStateTimelineReference
from jmoraIs.clinical_state.ports import ClinicalStateExactReferenceQueryPort
from jmoraIs.llm_human_review.domain import LLMHumanReviewEvent
from jmoraIs.llm_human_review.exact_reference import PersistedHumanReviewReference
from jmoraIs.llm_human_review.ports import HumanReviewExactQueryPort
from jmoraIs.medical_documents.domain import MedicalDocumentVersion
from jmoraIs.medical_documents.exact_reference import PersistedMedicalDocumentVersionReference
from jmoraIs.medical_documents.ports import MedicalDocumentExactQueryPort
from .viewers import ClinicalSummaryView, WorkspaceReadRejected, _require_reference


@dataclass(frozen=True)
class TimelineView:
    source_reference: PersistedClinicalStateTimelineReference
    entries: tuple[ClinicalSummaryView, ...]
    integrity_status: str = "OWNER_EXACT_REREAD"


@dataclass(frozen=True)
class MedicalDocumentView:
    source_reference: PersistedMedicalDocumentVersionReference
    status: str
    review_status: str
    validation_valid: bool
    provenance_references: tuple[str, ...]
    created_at: datetime
    integrity_status: str = "OWNER_EXACT_REREAD"


@dataclass(frozen=True)
class HumanReviewView:
    source_reference: PersistedHumanReviewReference
    decision: str
    resulting_state: str
    reviewer_role: str
    occurred_at: datetime
    integrity_status: str = "OWNER_EXACT_REREAD"
    audit_status: str = "OWNER_EXACT_CHAIN_VERIFIED"


@dataclass(frozen=True)
class AuditDefenseView:
    source_reference: PersistedDefensePackageReference
    state: DefenseReferenceState
    status: str
    review_status: str
    previous_package_id: str | None
    provenance_references: tuple[str, ...]
    stage11_document: MedicalDocumentView | None
    integrity_status: str = "OWNER_EXACT_REREAD"
    # Exact reread is not a global replay/completeness attestation.
    replay_status: str = "NOT_EVALUATED"
    completeness_verified: bool | None = None


class RemainingClinicalWorkspace:
    def __init__(self, clinical_states: ClinicalStateExactReferenceQueryPort,
                 documents: MedicalDocumentExactQueryPort, reviews: HumanReviewExactQueryPort,
                 defenses: AuditDefenseQueryPort):
        self._states = clinical_states
        self._documents = documents
        self._reviews = reviews
        self._defenses = defenses

    def timeline(self, reference: PersistedClinicalStateTimelineReference) -> TimelineView:
        _require_reference(reference, PersistedClinicalStateTimelineReference)
        values = self._states.get_timeline_exact(reference)
        if len(values) != len(reference.state_references):
            raise WorkspaceReadRejected("exact timeline members are unavailable")
        # Preserve the owner's version ordering, never sort or infer current state.
        entries = tuple(ClinicalSummaryView(ref, value.pseudonymous_patient_id,
            value.state_version, value.as_of, value.review_status.value,
            tuple(flag.flag_type.value for flag in value.quality_flags), value.provenance_references)
            for ref, value in zip(reference.state_references, values, strict=True))
        return TimelineView(reference, entries)

    def medical_document(self, reference: PersistedMedicalDocumentVersionReference) -> MedicalDocumentView:
        _require_reference(reference, PersistedMedicalDocumentVersionReference)
        value = self._documents.get_exact(reference)
        if not isinstance(value, MedicalDocumentVersion):
            raise WorkspaceReadRejected("exact Medical Document is unavailable")
        return MedicalDocumentView(reference, value.document.status.value, value.document.review_status.value,
            value.document.validation.valid, value.document.provenance_references, value.created_at)

    def human_review(self, reference: PersistedHumanReviewReference) -> HumanReviewView:
        _require_reference(reference, PersistedHumanReviewReference)
        value = self._reviews.get_exact(reference)
        if not isinstance(value, LLMHumanReviewEvent):
            raise WorkspaceReadRejected("exact Human Review is unavailable")
        return HumanReviewView(reference, value.decision.value, value.resulting_state.value,
                               value.reviewer_role.value, value.occurred_at)

    def audit_defense(self, reference: PersistedDefensePackageReference) -> AuditDefenseView:
        _require_reference(reference, PersistedDefensePackageReference)
        value = self._defenses.get_exact(reference)
        if not isinstance(value, DefensePackage):
            raise WorkspaceReadRejected("exact Audit Defense is unavailable")
        if reference.state is DefenseReferenceState.PRE_LINK:
            if value.stage11_document_reference is not None:
                raise WorkspaceReadRejected("PRE_LINK cannot contain a document link")
            document = None
        elif reference.state is DefenseReferenceState.STAGE11_LINKED:
            document = self.medical_document(value.stage11_document_reference)
        else:
            raise WorkspaceReadRejected("explicit persisted Defense state is required")
        return AuditDefenseView(reference, reference.state, value.defense.status.value,
            value.defense.review_status.value, value.previous_package_id,
            value.defense.provenance_references, document)
