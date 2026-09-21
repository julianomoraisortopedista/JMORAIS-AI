from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional
from jmoraIs.clinical.governed import HumanReviewStatus
from jmoraIs.guideline_engine.domain import PersistedGuidelineRecommendationSetReference
from jmoraIs.orthopedic_intelligence.domain import PersistedOrthopedicAssessmentSetReference

class MedicalDocumentError(RuntimeError):pass
class DocumentBoundaryRejected(MedicalDocumentError):pass
class DocumentVersionConflict(MedicalDocumentError):pass
class DocumentType(str,Enum):
    CLINICAL_REPORT="CLINICAL_REPORT";MEDICAL_SUMMARY="MEDICAL_SUMMARY";FOLLOW_UP_REPORT="FOLLOW_UP_REPORT";SURGICAL_HISTORY_SUMMARY="SURGICAL_HISTORY_SUMMARY";ORTHOPEDIC_ASSESSMENT_REPORT="ORTHOPEDIC_ASSESSMENT_REPORT";EVIDENCE_SUMMARY="EVIDENCE_SUMMARY";GUIDELINE_SUMMARY="GUIDELINE_SUMMARY";PROCEDURE_JUSTIFICATION_DRAFT="PROCEDURE_JUSTIFICATION_DRAFT";AUDIT_SUPPORT_DRAFT="AUDIT_SUPPORT_DRAFT"
class DocumentStatus(str,Enum):DRAFT="DRAFT";REVIEW_REQUIRED="REVIEW_REQUIRED";UNDER_REVIEW="UNDER_REVIEW";APPROVED_BY_REVIEWER="APPROVED_BY_REVIEWER";REJECTED_BY_REVIEWER="REJECTED_BY_REVIEWER";SUPERSEDED="SUPERSEDED"
class DocumentGuidelineLineageStatus(str,Enum):EXACT="EXACT";LEGACY_MISSING_GUIDELINE_SET_REFERENCE="LEGACY_MISSING_GUIDELINE_SET_REFERENCE"
class DocumentOrthopedicLineageStatus(str,Enum):EXACT="EXACT";LEGACY_MISSING_ORTHOPEDIC_ASSESSMENT_REFERENCE="LEGACY_MISSING_ORTHOPEDIC_ASSESSMENT_REFERENCE"
class FactEpistemicStatus(str,Enum):FACT_CONFIRMED="FACT_CONFIRMED";FACT_REPORTED="FACT_REPORTED";FACT_OBSERVED="FACT_OBSERVED";FACT_SUSPECTED="FACT_SUSPECTED";FACT_INFERRED="FACT_INFERRED";FACT_UNKNOWN="FACT_UNKNOWN"
class SourceType(str,Enum):PATIENT_CLINICAL_STATE="PATIENT_CLINICAL_STATE";GOVERNED_EVIDENCE="GOVERNED_EVIDENCE";GUIDELINE_RECOMMENDATION_SET="GUIDELINE_RECOMMENDATION_SET";ORTHOPEDIC_ASSESSMENT_SET="ORTHOPEDIC_ASSESSMENT_SET";TERMINOLOGY="TERMINOLOGY";CANONICAL_VANCOUVER="CANONICAL_VANCOUVER"
class MissingMarker(str,Enum):NOT_DOCUMENTED="NOT_DOCUMENTED";NOT_AVAILABLE="NOT_AVAILABLE";REVIEW_REQUIRED="REVIEW_REQUIRED"
class ValidationSeverity(str,Enum):INFO="INFO";WARNING="WARNING";CRITICAL="CRITICAL"
class DocumentAuditType(str,Enum):GENERATION="GENERATION";VALIDATION_FAILURE="VALIDATION_FAILURE";MISSING_DATA="MISSING_DATA";CONFLICTING_DATA="CONFLICTING_DATA";TERMINOLOGY_UNCERTAINTY="TERMINOLOGY_UNCERTAINTY";CITATION_INCLUDED="CITATION_INCLUDED";GUIDELINE_INCLUDED="GUIDELINE_INCLUDED";REVIEW_TRANSITION="REVIEW_TRANSITION";CORRECTION="CORRECTION";SUPERSESSION="SUPERSESSION"
@dataclass(frozen=True)
class DocumentFactReference:
    fact_id:str;statement:str;epistemic_status:FactEpistemicStatus;source_type:SourceType;source_reference_id:str;source_version:str;terminology_reference_ids:tuple[str,...];provenance_references:tuple[str,...]
    policy_version:str="MIP-08-CLINICAL-FACT-1";recorded_at:Optional[datetime]=None;data_quality_flags:tuple[str,...]=();review_status:Optional[str]=None;original_source_reference:Optional[str]=None
@dataclass(frozen=True)
class DocumentEvidenceReference:
    governed_evidence_id:str;evidence_package_id:str;pmid:Optional[str];doi:Optional[str];verification_status:str;canonical_vancouver:str;citation_reference_id:str;provenance_references:tuple[str,...]
    publication_identity_id:Optional[str]=None;pmcid:Optional[str]=None;vancouver_citation_id:Optional[str]=None
    formatter_version:Optional[str]=None;ledger_references:tuple[str,...]=();policy_version:Optional[str]=None
    source_version:Optional[str]=None;editorial_status:Optional[str]=None;review_required:bool=False
@dataclass(frozen=True)
class DocumentGuidelineReference:
    recommendation_id:str;guideline_id:str;organization:str;guideline_version:str;strength:str;review_status:HumanReviewStatus;conflict_references:tuple[str,...];limitation_references:tuple[str,...];provenance_references:tuple[str,...]
@dataclass(frozen=True)
class DocumentTerminologyReference:
    concept_id:str;display_name:str;original_term:Optional[str];version:str;mapping_status:str;confidence:str;review_required:bool;provenance_references:tuple[str,...]
    code_system:Optional[str]=None;policy_version:str="MIP-08-TERMINOLOGY-1"
@dataclass(frozen=True)
class DocumentLimitation:
    code:str;marker:MissingMarker;section_id:str;source_references:tuple[str,...]
@dataclass(frozen=True)
class DocumentSection:
    section_id:str;title:str;order:int;allowed_source_types:tuple[SourceType,...];facts:tuple[DocumentFactReference,...];evidence:tuple[DocumentEvidenceReference,...];guidelines:tuple[DocumentGuidelineReference,...];terminology:tuple[DocumentTerminologyReference,...];limitations:tuple[DocumentLimitation,...];provenance_references:tuple[str,...]
@dataclass(frozen=True)
class DocumentTemplate:
    template_id:str;document_type:DocumentType;template_version:str;section_order:tuple[str,...];required_sections:tuple[str,...];optional_sections:tuple[str,...];allowed_sources:tuple[tuple[str,tuple[SourceType,...]],...];formatting_rules:tuple[str,...];policy_version:str
@dataclass(frozen=True)
class DocumentValidationIssue:
    code:str;severity:ValidationSeverity;section_id:Optional[str];reference_ids:tuple[str,...]
@dataclass(frozen=True)
class DocumentValidationResult:
    valid:bool;issues:tuple[DocumentValidationIssue,...];validated_at:datetime;gate_version:str
@dataclass(frozen=True)
class TraceabilityEntry:
    rendered_element_id:str;source_references:tuple[str,...];terminology_references:tuple[str,...];policy_version:str;template_version:str
@dataclass(frozen=True)
class TraceabilityManifest:
    entries:tuple[TraceabilityEntry,...];generated_at:datetime
@dataclass(frozen=True)
class MedicalDocument:
    document_id:str;document_type:DocumentType;pseudonymous_patient_id:str;reasoning_input_id:str;reasoning_input_version:int;clinical_state_reference_id:str;clinical_state_version:int;orthopedic_assessment_set_id:Optional[str];orthopedic_assessment_version:Optional[int];terminology_versions:tuple[str,...];governed_evidence_ids:tuple[str,...];guideline_recommendation_ids:tuple[str,...];policy_versions:tuple[str,...];template_id:str;template_version:str;sections:tuple[DocumentSection,...];status:DocumentStatus;review_status:HumanReviewStatus;validation:DocumentValidationResult;traceability:TraceabilityManifest;generated_at:datetime;provenance_references:tuple[str,...];externally_valid:bool=False;guideline_recommendation_set_reference:Optional[PersistedGuidelineRecommendationSetReference]=None;orthopedic_assessment_set_reference:Optional[PersistedOrthopedicAssessmentSetReference]=None
@dataclass(frozen=True)
class MedicalDocumentVersion:
    version_id:str;document_stream_id:str;version:int;previous_version_id:Optional[str];document:MedicalDocument;corrected_section_ids:tuple[str,...];reviewer_id:Optional[str];justification:Optional[str];created_at:datetime
    @property
    def guideline_lineage_status(self):
        return DocumentGuidelineLineageStatus.EXACT if self.document.guideline_recommendation_set_reference else DocumentGuidelineLineageStatus.LEGACY_MISSING_GUIDELINE_SET_REFERENCE
    @property
    def orthopedic_lineage_status(self):
        return DocumentOrthopedicLineageStatus.EXACT if self.document.orthopedic_assessment_set_reference else DocumentOrthopedicLineageStatus.LEGACY_MISSING_ORTHOPEDIC_ASSESSMENT_REFERENCE
@dataclass(frozen=True)
class DocumentAuditEvent:
    event_id:str;document_stream_id:str;version_id:str;event_type:DocumentAuditType;occurred_at:datetime;actor_id:str;decision_code:str;reference_ids:tuple[str,...];policy_version:str
@dataclass(frozen=True)
class RenderedDocument:
    document_id:str;format:str;content:object;traceability:TraceabilityManifest
