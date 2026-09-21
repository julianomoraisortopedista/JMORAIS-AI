from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ApiModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ApiError(ApiModel):
    code: str
    message: str
    correlation_id: str


class HealthResponse(ApiModel):
    status: str


class ReadinessResponse(ApiModel):
    status: str
    api_version: str
    missing_dependencies: tuple[str, ...] = ()
    checks: tuple["ReadinessCheckResponse", ...] = ()


class ReadinessCheckResponse(ApiModel):
    name: str
    ready: bool
    code: str


class VersionResponse(ApiModel):
    service: str = "JMORAIS-AI internal API"
    api_version: str
    platform_version: str
    intended_use: str = "INTERNAL_DEVELOPMENT_ONLY"


class BuildResponse(ApiModel):
    release_id: str
    build_id: str
    source_revision: str
    built_at: str
    python_version: str
    migration_revision: str
    intended_use: str = "INTERNAL_ENGINEERING_ONLY"


class PageMetadata(ApiModel):
    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    returned: int = Field(ge=0)
    total: int = Field(ge=0)


class ClinicalReasoningInputResponse(ApiModel):
    contract_version: str = "v1"
    input_id: str
    subject_reference: str
    input_version: int
    previous_input_id: str | None
    clinical_state_reference_id: str
    clinical_state_version: int
    patient_context_version: int
    terminology_version: str
    governed_evidence_ids: tuple[str, ...]
    applicable_guideline_ids: tuple[str, ...]
    timeline_reference_id: str
    review_status: str
    readiness: str
    policy_versions: tuple[str, ...]
    provenance_reference_ids: tuple[str, ...]
    created_at: datetime


class GovernedEvidenceResponse(ApiModel):
    contract_version: str = "v1"
    governed_evidence_id: str
    evidence_level: str
    methodological_quality: str
    recommendation_strength: str
    applicability: tuple[str, ...]
    lifecycle_status: str
    support_directions: tuple[str, ...]
    provenance_references: tuple[str, ...]
    ledger_references: tuple[str, ...]
    policy_version: str
    appraisal_version: str
    limitations: tuple[str, ...]
    issued_at: datetime


class RecommendationReference(ApiModel):
    recommendation_id: str
    guideline_id: str
    guideline_version: str
    intent: str
    readiness: str
    review_status: str
    governed_evidence_ids: tuple[str, ...]
    provenance_references: tuple[str, ...]


class GuidelineRecommendationSetResponse(ApiModel):
    contract_version: str = "v1"
    set_id: str
    subject_reference: str
    set_version: int
    reasoning_input_id: str
    readiness: str
    review_status: str
    policy_version: str
    recommendations: tuple[RecommendationReference, ...]
    page: PageMetadata
    provenance_references: tuple[str, ...]
    generated_at: datetime


class OrthopedicAssessmentSetResponse(ApiModel):
    contract_version: str = "v1"
    set_id: str
    subject_reference: str
    set_version: int
    reasoning_input_id: str
    assessment_id: str
    readiness: str
    review_status: str
    terminology_version: str
    governed_evidence_ids: tuple[str, ...]
    guideline_recommendation_ids: tuple[str, ...]
    quality_flags: tuple[str, ...]
    limitations: tuple[str, ...]
    policy_version: str
    provenance_references: tuple[str, ...]
    generated_at: datetime


class DocumentSectionReference(ApiModel):
    section_id: str
    title: str
    order: int
    provenance_references: tuple[str, ...]


class MedicalDocumentResponse(ApiModel):
    contract_version: str = "v1"
    version_id: str
    document_stream_id: str
    version: int
    document_id: str
    document_type: str
    reasoning_input_id: str
    reasoning_input_version: int
    clinical_state_reference_id: str
    clinical_state_version: int
    status: str
    review_status: str
    validation_gate_version: str
    sections: tuple[DocumentSectionReference, ...]
    page: PageMetadata
    policy_versions: tuple[str, ...]
    provenance_references: tuple[str, ...]
    created_at: datetime


class DefenseArgumentReference(ApiModel):
    argument_id: str
    argument_code: str
    position: str
    provenance_references: tuple[str, ...]


class AuditDefenseResponse(ApiModel):
    contract_version: str = "v1"
    package_id: str
    stream_id: str
    version: int
    defense_id: str
    reasoning_input_id: str
    reasoning_input_version: int
    orthopedic_assessment_set_id: str
    status: str
    review_status: str
    arguments: tuple[DefenseArgumentReference, ...]
    page: PageMetadata
    provenance_references: tuple[str, ...]
    created_at: datetime
