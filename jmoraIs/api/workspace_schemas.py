"""Transport metadata only; the Clinical State owner authenticates references."""
from datetime import datetime

from pydantic import AwareDatetime, Field

from jmoraIs.clinical_state.exact_reference import PersistedClinicalStateReference
from .schemas import ApiModel


class ClinicalStateReferenceTransport(ApiModel):
    reference_id: str = Field(min_length=1, max_length=256, strict=True)
    state_id: str = Field(min_length=1, max_length=256, strict=True)
    state_version: int = Field(ge=1, strict=True)
    pseudonymous_patient_id: str = Field(min_length=1, max_length=256, strict=True)
    tenant_id: str = Field(min_length=1, max_length=256, strict=True)
    policy_version: str = Field(min_length=1, max_length=256, strict=True)
    predecessor_reference_id: str | None = Field(max_length=256, strict=True)
    predecessor_state_version: int | None = Field(ge=1, strict=True)
    provenance_reference: str = Field(min_length=1, max_length=512, strict=True)
    state_integrity_hash: str = Field(pattern=r"^[0-9a-f]{64}$", strict=True)
    integrity_hash: str = Field(pattern=r"^[0-9a-f]{64}$", strict=True)
    issued_at: AwareDatetime

    def to_reference(self) -> PersistedClinicalStateReference:
        # All fields are supplied by the caller, never inferred or re-issued.
        # This typed value remains untrusted until the owner exact read succeeds.
        return PersistedClinicalStateReference(**self.model_dump())


class ClinicalSummaryRequest(ApiModel):
    reference: ClinicalStateReferenceTransport


class ClinicalSummaryResponse(ApiModel):
    source_reference: ClinicalStateReferenceTransport
    pseudonymous_patient_id: str
    state_version: int
    as_of: datetime
    review_status: str
    quality_flags: tuple[str, ...]
    provenance_references: tuple[str, ...]
    integrity_status: str


# Full nested owner metadata is required; omitted fields are never backfilled.
from jmoraIs.appraisal.exact_reference import PersistedGovernedEvidenceReference
from jmoraIs.audit_defense.domain import DefenseReferenceState
from jmoraIs.audit_defense.domain import PersistedDefensePackageReference
from jmoraIs.clinical_state.exact_reference import PersistedClinicalStateTimelineReference
from jmoraIs.gateway_input import UpstreamArtifactReference
from jmoraIs.governed_llm_draft.exact_reference import PersistedGovernedLLMDraftReference
from jmoraIs.guideline_engine.domain import PersistedGuidelineRecommendationSetReference
from jmoraIs.llm_gateway.exact_reference import PersistedLLMInvocationReference
from jmoraIs.llm_human_review.exact_reference import PersistedHumanReviewReference
from jmoraIs.medical_documents.exact_reference import PersistedMedicalDocumentVersionReference
from jmoraIs.orthopedic_intelligence.domain import PersistedOrthopedicAssessmentSetReference
from jmoraIs.reasoning_input.exact_reference import PersistedClinicalReasoningInputReference
from jmoraIs.terminology.domain import MappingType
from jmoraIs.terminology.domain import PersistedTerminologyMappingGovernanceReference

class PersistedClinicalStateTimelineReferenceTransport(ApiModel):
    timeline_reference_id: str = Field(strict=True, max_length=4096)
    pseudonymous_patient_id: str = Field(strict=True, max_length=4096)
    tenant_id: str = Field(strict=True, max_length=4096)
    policy_version: str = Field(strict=True, max_length=4096)
    state_references: tuple[ClinicalStateReferenceTransport, ...]
    integrity_hash: str = Field(strict=True, max_length=4096)
    issued_at: AwareDatetime

    def to_reference(self) -> PersistedClinicalStateTimelineReference:
        return PersistedClinicalStateTimelineReference(
            timeline_reference_id=self.timeline_reference_id,
            pseudonymous_patient_id=self.pseudonymous_patient_id,
            tenant_id=self.tenant_id,
            policy_version=self.policy_version,
            state_references=tuple(item.to_reference() for item in self.state_references),
            integrity_hash=self.integrity_hash,
            issued_at=self.issued_at,
        )


class TimelineResponse(ApiModel):
    source_reference: PersistedClinicalStateTimelineReferenceTransport
    entries: tuple[ClinicalSummaryResponse, ...]
    integrity_status: str = Field(strict=True, max_length=4096)


class PersistedGovernedEvidenceReferenceTransport(ApiModel):
    reference_id: str = Field(strict=True, max_length=4096)
    governed_evidence_id: str = Field(strict=True, max_length=4096)
    stream_version: int = Field(strict=True)
    tenant_id: str = Field(strict=True, max_length=4096)
    evidence_package_id: str = Field(strict=True, max_length=4096)
    appraisal_record_id: str = Field(strict=True, max_length=4096)
    appraisal_record_version: int = Field(strict=True)
    policy_version: str = Field(strict=True, max_length=4096)
    lifecycle_event_id: str = Field(strict=True, max_length=4096)
    lifecycle_status: str = Field(strict=True, max_length=4096)
    lifecycle_integrity_hash: str = Field(strict=True, max_length=4096)
    provenance_reference: str = Field(strict=True, max_length=4096)
    governed_evidence_integrity_hash: str = Field(strict=True, max_length=4096)
    integrity_hash: str = Field(strict=True, max_length=4096)
    issued_at: AwareDatetime

    def to_reference(self) -> PersistedGovernedEvidenceReference:
        return PersistedGovernedEvidenceReference(
            reference_id=self.reference_id,
            governed_evidence_id=self.governed_evidence_id,
            stream_version=self.stream_version,
            tenant_id=self.tenant_id,
            evidence_package_id=self.evidence_package_id,
            appraisal_record_id=self.appraisal_record_id,
            appraisal_record_version=self.appraisal_record_version,
            policy_version=self.policy_version,
            lifecycle_event_id=self.lifecycle_event_id,
            lifecycle_status=self.lifecycle_status,
            lifecycle_integrity_hash=self.lifecycle_integrity_hash,
            provenance_reference=self.provenance_reference,
            governed_evidence_integrity_hash=self.governed_evidence_integrity_hash,
            integrity_hash=self.integrity_hash,
            issued_at=self.issued_at,
        )


class EvidenceResponse(ApiModel):
    source_reference: PersistedGovernedEvidenceReferenceTransport
    evidence_level: str = Field(strict=True, max_length=4096)
    methodological_quality: str = Field(strict=True, max_length=4096)
    recommendation_strength: str = Field(strict=True, max_length=4096)
    guideline_governance_status: str = Field(strict=True, max_length=4096)
    applicability: tuple[str, ...]
    support_directions: tuple[str, ...]
    conflict_status: tuple[str, ...]
    limitations: tuple[str, ...]
    provenance_references: tuple[str, ...]
    ledger_references: tuple[str, ...]
    integrity_status: str = Field(strict=True, max_length=4096)


class PersistedTerminologyMappingGovernanceReferenceTransport(ApiModel):
    reference_id: str = Field(strict=True, max_length=4096)
    governance_record_id: str = Field(strict=True, max_length=4096)
    record_version: int = Field(strict=True)
    target_concept_id: str | None
    terminology_version: str = Field(strict=True, max_length=4096)
    source_reference: str = Field(strict=True, max_length=4096)
    mapping_type: MappingType
    classification: str = Field(strict=True, max_length=4096)
    policy_version: str = Field(strict=True, max_length=4096)
    integrity_hash: str = Field(strict=True, max_length=4096)
    issued_at: AwareDatetime

    def to_reference(self) -> PersistedTerminologyMappingGovernanceReference:
        return PersistedTerminologyMappingGovernanceReference(
            reference_id=self.reference_id,
            governance_record_id=self.governance_record_id,
            record_version=self.record_version,
            target_concept_id=(self.target_concept_id if self.target_concept_id is not None else None),
            terminology_version=self.terminology_version,
            source_reference=self.source_reference,
            mapping_type=self.mapping_type,
            classification=self.classification,
            policy_version=self.policy_version,
            integrity_hash=self.integrity_hash,
            issued_at=self.issued_at,
        )


class PersistedClinicalReasoningInputReferenceTransport(ApiModel):
    reference_id: str = Field(strict=True, max_length=4096)
    input_id: str = Field(strict=True, max_length=4096)
    input_version: int = Field(strict=True)
    previous_input_id: str | None
    predecessor_reference_id: str | None
    subject_reference: str = Field(strict=True, max_length=4096)
    tenant_id: str = Field(strict=True, max_length=4096)
    policy_version: str = Field(strict=True, max_length=4096)
    provenance_reference: str = Field(strict=True, max_length=4096)
    input_integrity_hash: str = Field(strict=True, max_length=4096)
    clinical_state_reference: ClinicalStateReferenceTransport
    governed_evidence_references: tuple[PersistedGovernedEvidenceReferenceTransport, ...]
    terminology_governance_references: tuple[PersistedTerminologyMappingGovernanceReferenceTransport, ...]
    integrity_hash: str = Field(strict=True, max_length=4096)
    issued_at: AwareDatetime

    def to_reference(self) -> PersistedClinicalReasoningInputReference:
        return PersistedClinicalReasoningInputReference(
            reference_id=self.reference_id,
            input_id=self.input_id,
            input_version=self.input_version,
            previous_input_id=(self.previous_input_id if self.previous_input_id is not None else None),
            predecessor_reference_id=(self.predecessor_reference_id if self.predecessor_reference_id is not None else None),
            subject_reference=self.subject_reference,
            tenant_id=self.tenant_id,
            policy_version=self.policy_version,
            provenance_reference=self.provenance_reference,
            input_integrity_hash=self.input_integrity_hash,
            clinical_state_reference=self.clinical_state_reference.to_reference(),
            governed_evidence_references=tuple(item.to_reference() for item in self.governed_evidence_references),
            terminology_governance_references=tuple(item.to_reference() for item in self.terminology_governance_references),
            integrity_hash=self.integrity_hash,
            issued_at=self.issued_at,
        )


class ExplainabilityResponse(ApiModel):
    source_reference: PersistedClinicalReasoningInputReferenceTransport
    review_status: str = Field(strict=True, max_length=4096)
    readiness: str = Field(strict=True, max_length=4096)
    missing_data_references: tuple[str, ...]
    conflicting_data_references: tuple[str, ...]
    stale_data_references: tuple[str, ...]
    review_required: bool = Field(strict=True)
    integrity_status: str = Field(strict=True, max_length=4096)


class PersistedGuidelineRecommendationSetReferenceTransport(ApiModel):
    reference_id: str = Field(strict=True, max_length=4096)
    set_id: str = Field(strict=True, max_length=4096)
    set_version: int = Field(strict=True)
    subject_reference: str = Field(strict=True, max_length=4096)
    tenant_id: str = Field(strict=True, max_length=4096)
    policy_version: str = Field(strict=True, max_length=4096)
    integrity_hash: str = Field(strict=True, max_length=4096)
    issued_at: AwareDatetime

    def to_reference(self) -> PersistedGuidelineRecommendationSetReference:
        return PersistedGuidelineRecommendationSetReference(
            reference_id=self.reference_id,
            set_id=self.set_id,
            set_version=self.set_version,
            subject_reference=self.subject_reference,
            tenant_id=self.tenant_id,
            policy_version=self.policy_version,
            integrity_hash=self.integrity_hash,
            issued_at=self.issued_at,
        )


class PersistedOrthopedicAssessmentSetReferenceTransport(ApiModel):
    reference_id: str = Field(strict=True, max_length=4096)
    set_id: str = Field(strict=True, max_length=4096)
    set_version: int = Field(strict=True)
    subject_reference: str = Field(strict=True, max_length=4096)
    tenant_id: str = Field(strict=True, max_length=4096)
    policy_version: str = Field(strict=True, max_length=4096)
    integrity_hash: str = Field(strict=True, max_length=4096)
    issued_at: AwareDatetime

    def to_reference(self) -> PersistedOrthopedicAssessmentSetReference:
        return PersistedOrthopedicAssessmentSetReference(
            reference_id=self.reference_id,
            set_id=self.set_id,
            set_version=self.set_version,
            subject_reference=self.subject_reference,
            tenant_id=self.tenant_id,
            policy_version=self.policy_version,
            integrity_hash=self.integrity_hash,
            issued_at=self.issued_at,
        )


class PersistedMedicalDocumentVersionReferenceTransport(ApiModel):
    reference_id: str = Field(strict=True, max_length=4096)
    document_stream_id: str = Field(strict=True, max_length=4096)
    document_id: str = Field(strict=True, max_length=4096)
    version_id: str = Field(strict=True, max_length=4096)
    version: int = Field(strict=True)
    predecessor: str | None
    tenant_id: str = Field(strict=True, max_length=4096)
    policy_version: str = Field(strict=True, max_length=4096)
    document_type: str = Field(strict=True, max_length=4096)
    validation_status: str = Field(strict=True, max_length=4096)
    review_status: str = Field(strict=True, max_length=4096)
    document_integrity_hash: str = Field(strict=True, max_length=4096)
    provenance_reference: str = Field(strict=True, max_length=4096)
    reasoning_input_id: str = Field(strict=True, max_length=4096)
    reasoning_input_version: int = Field(strict=True)
    clinical_state_reference_id: str = Field(strict=True, max_length=4096)
    clinical_state_version: int = Field(strict=True)
    guideline_reference: PersistedGuidelineRecommendationSetReferenceTransport | None
    orthopedic_reference: PersistedOrthopedicAssessmentSetReferenceTransport | None
    traceability_hash: str = Field(strict=True, max_length=4096)
    integrity_hash: str = Field(strict=True, max_length=4096)
    issued_at: AwareDatetime

    def to_reference(self) -> PersistedMedicalDocumentVersionReference:
        return PersistedMedicalDocumentVersionReference(
            reference_id=self.reference_id,
            document_stream_id=self.document_stream_id,
            document_id=self.document_id,
            version_id=self.version_id,
            version=self.version,
            predecessor=(self.predecessor if self.predecessor is not None else None),
            tenant_id=self.tenant_id,
            policy_version=self.policy_version,
            document_type=self.document_type,
            validation_status=self.validation_status,
            review_status=self.review_status,
            document_integrity_hash=self.document_integrity_hash,
            provenance_reference=self.provenance_reference,
            reasoning_input_id=self.reasoning_input_id,
            reasoning_input_version=self.reasoning_input_version,
            clinical_state_reference_id=self.clinical_state_reference_id,
            clinical_state_version=self.clinical_state_version,
            guideline_reference=(self.guideline_reference.to_reference() if self.guideline_reference is not None else None),
            orthopedic_reference=(self.orthopedic_reference.to_reference() if self.orthopedic_reference is not None else None),
            traceability_hash=self.traceability_hash,
            integrity_hash=self.integrity_hash,
            issued_at=self.issued_at,
        )


class MedicalDocumentResponse(ApiModel):
    source_reference: PersistedMedicalDocumentVersionReferenceTransport
    status: str = Field(strict=True, max_length=4096)
    review_status: str = Field(strict=True, max_length=4096)
    validation_valid: bool = Field(strict=True)
    provenance_references: tuple[str, ...]
    created_at: AwareDatetime
    integrity_status: str = Field(strict=True, max_length=4096)


class UpstreamArtifactReferenceTransport(ApiModel):
    artifact_type: str = Field(strict=True, max_length=4096)
    artifact_id: str = Field(strict=True, max_length=4096)
    artifact_version: int = Field(strict=True)
    tenant_id: str = Field(strict=True, max_length=4096)
    integrity_reference: str = Field(strict=True, max_length=4096)
    policy_version: str = Field(strict=True, max_length=4096)
    source_context: str = Field(strict=True, max_length=4096)

    def to_reference(self) -> UpstreamArtifactReference:
        return UpstreamArtifactReference(
            artifact_type=self.artifact_type,
            artifact_id=self.artifact_id,
            artifact_version=self.artifact_version,
            tenant_id=self.tenant_id,
            integrity_reference=self.integrity_reference,
            policy_version=self.policy_version,
            source_context=self.source_context,
        )


class PersistedLLMInvocationReferenceTransport(ApiModel):
    reference_id: str = Field(strict=True, max_length=4096)
    invocation_id: str = Field(strict=True, max_length=4096)
    request_id: str = Field(strict=True, max_length=4096)
    correlation_id: str = Field(strict=True, max_length=4096)
    tenant_id: str = Field(strict=True, max_length=4096)
    principal_id: str = Field(strict=True, max_length=4096)
    purpose: str = Field(strict=True, max_length=4096)
    prompt_version_id: str = Field(strict=True, max_length=4096)
    prompt_template_id: str = Field(strict=True, max_length=4096)
    prompt_version: int = Field(strict=True)
    prompt_hash: str = Field(strict=True, max_length=4096)
    persisted_gateway_input_id: str = Field(strict=True, max_length=4096)
    upstream_artifact_reference: UpstreamArtifactReferenceTransport
    provider: str = Field(strict=True, max_length=4096)
    model_id: str = Field(strict=True, max_length=4096)
    policy_version: str = Field(strict=True, max_length=4096)
    output_classification: str = Field(strict=True, max_length=4096)
    invocation_status: str = Field(strict=True, max_length=4096)
    temperature: float = Field(strict=True)
    seed: int | None
    invocation_integrity_hash: str = Field(strict=True, max_length=4096)
    integrity_hash: str = Field(strict=True, max_length=4096)
    issued_at: AwareDatetime

    def to_reference(self) -> PersistedLLMInvocationReference:
        return PersistedLLMInvocationReference(
            reference_id=self.reference_id,
            invocation_id=self.invocation_id,
            request_id=self.request_id,
            correlation_id=self.correlation_id,
            tenant_id=self.tenant_id,
            principal_id=self.principal_id,
            purpose=self.purpose,
            prompt_version_id=self.prompt_version_id,
            prompt_template_id=self.prompt_template_id,
            prompt_version=self.prompt_version,
            prompt_hash=self.prompt_hash,
            persisted_gateway_input_id=self.persisted_gateway_input_id,
            upstream_artifact_reference=self.upstream_artifact_reference.to_reference(),
            provider=self.provider,
            model_id=self.model_id,
            policy_version=self.policy_version,
            output_classification=self.output_classification,
            invocation_status=self.invocation_status,
            temperature=self.temperature,
            seed=(self.seed if self.seed is not None else None),
            invocation_integrity_hash=self.invocation_integrity_hash,
            integrity_hash=self.integrity_hash,
            issued_at=self.issued_at,
        )


class PersistedGovernedLLMDraftReferenceTransport(ApiModel):
    reference_id: str = Field(strict=True, max_length=4096)
    draft_id: str = Field(strict=True, max_length=4096)
    draft_stream_id: str = Field(strict=True, max_length=4096)
    draft_version: int = Field(strict=True)
    predecessor: str | None
    tenant_id: str = Field(strict=True, max_length=4096)
    invocation_id: str = Field(strict=True, max_length=4096)
    request_id: str = Field(strict=True, max_length=4096)
    correlation_id: str = Field(strict=True, max_length=4096)
    persisted_gateway_input_id: str = Field(strict=True, max_length=4096)
    upstream_artifact_reference: UpstreamArtifactReferenceTransport
    policy_version: str = Field(strict=True, max_length=4096)
    lifecycle_event_id: str = Field(strict=True, max_length=4096)
    lifecycle_status: str = Field(strict=True, max_length=4096)
    lifecycle_integrity_hash: str = Field(strict=True, max_length=4096)
    reviewable_content_hash: str = Field(strict=True, max_length=4096)
    draft_integrity_hash: str = Field(strict=True, max_length=4096)
    provenance_reference: str = Field(strict=True, max_length=4096)
    integrity_hash: str = Field(strict=True, max_length=4096)
    issued_at: AwareDatetime
    invocation_reference: PersistedLLMInvocationReferenceTransport | None

    def to_reference(self) -> PersistedGovernedLLMDraftReference:
        return PersistedGovernedLLMDraftReference(
            reference_id=self.reference_id,
            draft_id=self.draft_id,
            draft_stream_id=self.draft_stream_id,
            draft_version=self.draft_version,
            predecessor=(self.predecessor if self.predecessor is not None else None),
            tenant_id=self.tenant_id,
            invocation_id=self.invocation_id,
            request_id=self.request_id,
            correlation_id=self.correlation_id,
            persisted_gateway_input_id=self.persisted_gateway_input_id,
            upstream_artifact_reference=self.upstream_artifact_reference.to_reference(),
            policy_version=self.policy_version,
            lifecycle_event_id=self.lifecycle_event_id,
            lifecycle_status=self.lifecycle_status,
            lifecycle_integrity_hash=self.lifecycle_integrity_hash,
            reviewable_content_hash=self.reviewable_content_hash,
            draft_integrity_hash=self.draft_integrity_hash,
            provenance_reference=self.provenance_reference,
            integrity_hash=self.integrity_hash,
            issued_at=self.issued_at,
            invocation_reference=(self.invocation_reference.to_reference() if self.invocation_reference is not None else None),
        )


class PersistedHumanReviewReferenceTransport(ApiModel):
    reference_id: str = Field(strict=True, max_length=4096)
    review_event_id: str = Field(strict=True, max_length=4096)
    draft_reference: PersistedGovernedLLMDraftReferenceTransport
    stream_position: int = Field(strict=True)
    tenant_id: str = Field(strict=True, max_length=4096)
    reviewer_id: str = Field(strict=True, max_length=4096)
    reviewer_role: str = Field(strict=True, max_length=4096)
    decision: str = Field(strict=True, max_length=4096)
    resulting_state: str = Field(strict=True, max_length=4096)
    policy_version: str = Field(strict=True, max_length=4096)
    request_id: str = Field(strict=True, max_length=4096)
    correlation_id: str = Field(strict=True, max_length=4096)
    predecessor_event_id: str | None
    previous_hash: str | None
    event_integrity_hash: str = Field(strict=True, max_length=4096)
    integrity_hash: str = Field(strict=True, max_length=4096)
    issued_at: AwareDatetime

    def to_reference(self) -> PersistedHumanReviewReference:
        return PersistedHumanReviewReference(
            reference_id=self.reference_id,
            review_event_id=self.review_event_id,
            draft_reference=self.draft_reference.to_reference(),
            stream_position=self.stream_position,
            tenant_id=self.tenant_id,
            reviewer_id=self.reviewer_id,
            reviewer_role=self.reviewer_role,
            decision=self.decision,
            resulting_state=self.resulting_state,
            policy_version=self.policy_version,
            request_id=self.request_id,
            correlation_id=self.correlation_id,
            predecessor_event_id=(self.predecessor_event_id if self.predecessor_event_id is not None else None),
            previous_hash=(self.previous_hash if self.previous_hash is not None else None),
            event_integrity_hash=self.event_integrity_hash,
            integrity_hash=self.integrity_hash,
            issued_at=self.issued_at,
        )


class HumanReviewResponse(ApiModel):
    source_reference: PersistedHumanReviewReferenceTransport
    decision: str = Field(strict=True, max_length=4096)
    resulting_state: str = Field(strict=True, max_length=4096)
    reviewer_role: str = Field(strict=True, max_length=4096)
    occurred_at: AwareDatetime
    integrity_status: str = Field(strict=True, max_length=4096)
    audit_status: str = Field(strict=True, max_length=4096)


class PersistedDefensePackageReferenceTransport(ApiModel):
    reference_id: str = Field(strict=True, max_length=4096)
    stream_id: str = Field(strict=True, max_length=4096)
    version: int = Field(strict=True)
    package_id: str = Field(strict=True, max_length=4096)
    tenant_id: str = Field(strict=True, max_length=4096)
    policy_version: str = Field(strict=True, max_length=4096)
    integrity_hash: str = Field(strict=True, max_length=4096)
    issued_at: AwareDatetime
    state: DefenseReferenceState | None

    def to_reference(self) -> PersistedDefensePackageReference:
        return PersistedDefensePackageReference(
            reference_id=self.reference_id,
            stream_id=self.stream_id,
            version=self.version,
            package_id=self.package_id,
            tenant_id=self.tenant_id,
            policy_version=self.policy_version,
            integrity_hash=self.integrity_hash,
            issued_at=self.issued_at,
            state=(self.state if self.state is not None else None),
        )


class AuditDefenseResponse(ApiModel):
    source_reference: PersistedDefensePackageReferenceTransport
    state: DefenseReferenceState
    status: str = Field(strict=True, max_length=4096)
    review_status: str = Field(strict=True, max_length=4096)
    previous_package_id: str | None
    provenance_references: tuple[str, ...]
    stage11_document: MedicalDocumentResponse | None
    integrity_status: str = Field(strict=True, max_length=4096)
    replay_status: str = Field(strict=True, max_length=4096)
    completeness_verified: bool | None


class TimelineRequest(ApiModel):
    reference: PersistedClinicalStateTimelineReferenceTransport


class EvidenceRequest(ApiModel):
    reference: PersistedGovernedEvidenceReferenceTransport


class ExplainabilityRequest(ApiModel):
    reference: PersistedClinicalReasoningInputReferenceTransport


class MedicalDocumentRequest(ApiModel):
    reference: PersistedMedicalDocumentVersionReferenceTransport


class HumanReviewRequest(ApiModel):
    reference: PersistedHumanReviewReferenceTransport


class AuditDefenseRequest(ApiModel):
    reference: PersistedDefensePackageReferenceTransport


class WorkspaceContextResponse(ApiModel):
    caller_id: str
    tenant_id: str
    organization_id: str
    role: str
    purpose: str
    permissions: tuple[str, ...]
