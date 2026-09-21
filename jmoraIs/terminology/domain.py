from __future__ import annotations
from dataclasses import dataclass
from datetime import date,datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

class TerminologyError(RuntimeError):pass
class TerminologyVersionConflict(TerminologyError):pass
class InvalidTerminologyRecord(TerminologyError):pass
class UnknownUnitConversion(TerminologyError):pass

class CodeSystem(str,Enum):
    ICD_10="ICD-10";ICD_11="ICD-11";SNOMED_CT="SNOMED_CT";LOINC="LOINC";RXNORM="RxNorm";ATC="ATC";UCUM="UCUM";TUSS="TUSS";CPT="CPT_REFERENCE_ONLY";ORTHOPEDIC="JMORAIS_ORTHOPEDIC"
class TerminologyStatus(str,Enum):
    ACTIVE="ACTIVE";DEPRECATED="DEPRECATED";SUPERSEDED="SUPERSEDED";RETIRED="RETIRED";UNKNOWN="UNKNOWN"
class MappingConfidence(str,Enum):HIGH="HIGH";MEDIUM="MEDIUM";LOW="LOW";UNKNOWN="UNKNOWN"
class MappingOutcome(str,Enum):MAPPED="MAPPED";REVIEW_REQUIRED="REVIEW_REQUIRED";UNKNOWN="UNKNOWN"
class MappingType(str,Enum):EXACT="EXACT";EQUIVALENT="EQUIVALENT";BROADER="BROADER";NARROWER="NARROWER";RELATED="RELATED";UNMAPPED="UNMAPPED"
class MappingReviewStatus(str,Enum):AUTO_MAPPED="AUTO_MAPPED";REVIEW_REQUIRED="REVIEW_REQUIRED";REVIEWED="REVIEWED";REJECTED="REJECTED"
class RelationshipType(str,Enum):IS_A="IS_A";PART_OF="PART_OF";EQUIVALENT_TO="EQUIVALENT_TO";RELATED_TO="RELATED_TO";SUPERSEDED_BY="SUPERSEDED_BY"
class OrthopedicCategory(str,Enum):
    BONE="BONE";JOINT="JOINT";LIGAMENT="LIGAMENT";TENDON="TENDON";CARTILAGE="CARTILAGE";MENISCUS="MENISCUS";MUSCLE="MUSCLE"
    LATERALITY="LATERALITY";BODY_REGION="BODY_REGION";ROM="ROM";ALIGNMENT="ALIGNMENT";INSTABILITY="INSTABILITY"
    SPORTS_ACTIVITY="SPORTS_ACTIVITY";FUNCTIONAL_LIMITATION="FUNCTIONAL_LIMITATION"
class TerminologyAuditType(str,Enum):MAPPING="MAPPING";NORMALIZATION="NORMALIZATION";VALIDATION="VALIDATION";VERSION_LOOKUP="VERSION_LOOKUP";AMBIGUOUS_MAPPING="AMBIGUOUS_MAPPING"

def _text(value,name):
    if not isinstance(value,str) or not value.strip():raise InvalidTerminologyRecord(f"{name} is required")
def _aware(value,name):
    if value.tzinfo is None:raise InvalidTerminologyRecord(f"{name} must be timezone-aware")

@dataclass(frozen=True)
class TerminologySource:
    source_id:str;name:str;release_reference:str;license_reference:str;retrieved_at:datetime;provenance:str
    def __post_init__(self):
        for value,name in ((self.source_id,"source_id"),(self.name,"name"),(self.release_reference,"release_reference"),(self.license_reference,"license_reference"),(self.provenance,"provenance")):_text(value,name)
        _aware(self.retrieved_at,"retrieved_at")
@dataclass(frozen=True)
class TerminologyVersion:
    version_id:str;code_system:CodeSystem;version:str;effective_date:date;retirement_date:Optional[date];status:TerminologyStatus;source:TerminologySource;provenance:str
    def __post_init__(self):
        for value,name in ((self.version_id,"version_id"),(self.version,"version"),(self.provenance,"provenance")):_text(value,name)
        if self.retirement_date and self.retirement_date<self.effective_date:raise InvalidTerminologyRecord("retirement cannot precede effective date")
@dataclass(frozen=True)
class TerminologyCode:
    code_system:CodeSystem;code:str;version:str;display:str
    def __post_init__(self):
        for value,name in ((self.code,"code"),(self.version,"version"),(self.display,"display")):_text(value,name)
@dataclass(frozen=True)
class ClinicalConcept:
    canonical_id:str;display_name:str;preferred_term:str;synonyms:tuple[str,...];code_system:CodeSystem;version:str
    status:TerminologyStatus;effective_date:date;retirement_date:Optional[date];source:TerminologySource;provenance:str
    codes:tuple[TerminologyCode,...];orthopedic_category:Optional[OrthopedicCategory]=None;superseded_by:Optional[str]=None
    def __post_init__(self):
        for value,name in ((self.canonical_id,"canonical_id"),(self.display_name,"display_name"),(self.preferred_term,"preferred_term"),(self.version,"version"),(self.provenance,"provenance")):_text(value,name)
        if not self.codes or any(item.code_system is not self.code_system for item in self.codes):raise InvalidTerminologyRecord("concept requires codes from its declared code system")
        if len({item.casefold() for item in self.synonyms})!=len(self.synonyms):raise InvalidTerminologyRecord("concept synonyms must be unique")
        if self.retirement_date and self.retirement_date<self.effective_date:raise InvalidTerminologyRecord("retirement cannot precede effective date")
        if self.status is TerminologyStatus.SUPERSEDED and not self.superseded_by:raise InvalidTerminologyRecord("superseded concept requires successor reference")
@dataclass(frozen=True)
class ConceptMapping:
    mapping_id:str;source_codes:tuple[TerminologyCode,...];target_codes:tuple[TerminologyCode,...]
    confidence:MappingConfidence;status:TerminologyStatus;effective_date:date;retirement_date:Optional[date]
    source:TerminologySource;provenance:str
    def __post_init__(self):
        _text(self.mapping_id,"mapping_id");_text(self.provenance,"provenance")
        if not self.source_codes:raise InvalidTerminologyRecord("mapping requires source codes")
        if self.retirement_date and self.retirement_date<self.effective_date:raise InvalidTerminologyRecord("mapping retirement is invalid")
@dataclass(frozen=True)
class ConceptRelationship:
    relationship_id:str;source_concept_id:str;target_concept_id:str;relationship_type:RelationshipType
    version:str;effective_date:date;status:TerminologyStatus;source:TerminologySource;provenance:str
@dataclass(frozen=True)
class MappedClinicalConcept:
    original_term:str;requested_code_system:CodeSystem;terminology_version:str;outcome:MappingOutcome
    candidates:tuple[ClinicalConcept,...];selected_concept_id:Optional[str];confidence:MappingConfidence;review_required:bool
    provenance_references:tuple[str,...]
    def __post_init__(self):
        _text(self.original_term,"original_term");_text(self.terminology_version,"terminology_version")
        if self.outcome is MappingOutcome.MAPPED and (len(self.candidates)!=1 or self.selected_concept_id!=self.candidates[0].canonical_id):raise InvalidTerminologyRecord("mapped outcome requires exactly one selected candidate")
        if self.outcome is MappingOutcome.REVIEW_REQUIRED and (len(self.candidates)<2 or not self.review_required):raise InvalidTerminologyRecord("ambiguous outcome must retain candidates for review")
        if self.outcome is MappingOutcome.UNKNOWN and (self.candidates or self.selected_concept_id):raise InvalidTerminologyRecord("unknown mapping cannot invent candidates")
@dataclass(frozen=True)
class UnitNormalization:
    original_value:Decimal;original_unit:str;normalized_value:Decimal;normalized_unit:str
    conversion_provenance:str;ucum_version:str
    def __post_init__(self):
        for value,name in ((self.original_unit,"original_unit"),(self.normalized_unit,"normalized_unit"),(self.conversion_provenance,"conversion_provenance"),(self.ucum_version,"ucum_version")):_text(value,name)
@dataclass(frozen=True)
class UnitConversionRule:
    source_unit:str;target_unit:str;factor:Decimal;offset:Decimal;ucum_version:str;provenance:str
@dataclass(frozen=True)
class TerminologyAuditEvent:
    event_id:str;event_type:TerminologyAuditType;subject_reference:str;occurred_at:datetime;actor_id:str
    version_reference:str;outcome:str;provenance:str
@dataclass(frozen=True)
class ConceptValidation:
    canonical_id:str;valid:bool;status:TerminologyStatus;issues:tuple[str,...];validated_at:datetime

@dataclass(frozen=True)
class TerminologyMappingGovernanceRecord:
    governance_record_id:str;source_reference:str;source_term:str;source_code_system:Optional[CodeSystem]
    target_concept_id:Optional[str];terminology_version:str;mapping_type:MappingType;mapping_confidence:MappingConfidence
    review_status:MappingReviewStatus;review_required:bool;reviewer_reference:Optional[str];mapping_method:str
    policy_version:str;provenance_references:tuple[str,...];created_at:datetime;version:int
    predecessor_record_id:Optional[str];integrity_hash:str
    def __post_init__(self):
        for value,name in ((self.governance_record_id,"governance_record_id"),(self.source_reference,"source_reference"),(self.source_term,"source_term"),(self.terminology_version,"terminology_version"),(self.mapping_method,"mapping_method"),(self.policy_version,"policy_version"),(self.integrity_hash,"integrity_hash")):_text(value,name)
        _aware(self.created_at,"created_at")
        if self.version<1 or (self.version==1 and self.predecessor_record_id is not None) or (self.version>1 and not self.predecessor_record_id):raise InvalidTerminologyRecord("mapping governance version chain is invalid")
        if not self.provenance_references:raise InvalidTerminologyRecord("mapping governance provenance is required")
        if self.mapping_type is MappingType.UNMAPPED and self.target_concept_id is not None:raise InvalidTerminologyRecord("unmapped governance cannot select a concept")
        if self.mapping_type is not MappingType.UNMAPPED and not self.target_concept_id:raise InvalidTerminologyRecord("mapped governance requires a target concept")
        if self.review_status is MappingReviewStatus.REVIEW_REQUIRED and not self.review_required:raise InvalidTerminologyRecord("review-required governance must remain explicit")
        if self.review_required and self.review_status not in {MappingReviewStatus.REVIEW_REQUIRED,MappingReviewStatus.REJECTED}:raise InvalidTerminologyRecord("review requirement and review status conflict")
        if self.review_status in {MappingReviewStatus.REVIEWED,MappingReviewStatus.REJECTED} and not self.reviewer_reference:raise InvalidTerminologyRecord("reviewed mapping requires reviewer attribution")

@dataclass(frozen=True)
class PersistedTerminologyMappingGovernanceReference:
    reference_id:str;governance_record_id:str;record_version:int;target_concept_id:Optional[str]
    terminology_version:str;source_reference:str;mapping_type:MappingType;classification:str
    policy_version:str;integrity_hash:str;issued_at:datetime

@dataclass(frozen=True)
class GovernedTerminologyReference:
    concept:ClinicalConcept;governance_record_id:str;mapping_type:MappingType;mapping_confidence:MappingConfidence
    review_status:MappingReviewStatus;review_required:bool;policy_version:str;provenance_references:tuple[str,...]
    mapping_method:str;governance_version:int;created_at:datetime
