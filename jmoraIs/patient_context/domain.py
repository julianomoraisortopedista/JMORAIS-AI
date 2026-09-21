from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
import re
from typing import Optional


class PatientContextInvariantError(ValueError): pass


class Sex(str, Enum):
    FEMALE="FEMALE"; MALE="MALE"; INTERSEX="INTERSEX"; UNKNOWN="UNKNOWN"; NOT_REPORTED="NOT_REPORTED"
class Laterality(str, Enum):
    LEFT="LEFT"; RIGHT="RIGHT"; BILATERAL="BILATERAL"; MIDLINE="MIDLINE"; NOT_APPLICABLE="NOT_APPLICABLE"
class EncounterType(str, Enum):
    CONSULTATION="CONSULTATION"; EXAM="EXAM"; PROCEDURE="PROCEDURE"; SURGERY="SURGERY"; FOLLOW_UP="FOLLOW_UP"; COMPLICATION="COMPLICATION"; RECOVERY="RECOVERY"
class ImagingModality(str, Enum):
    XRAY="XRAY"; MRI="MRI"; CT="CT"; ULTRASOUND="ULTRASOUND"; BONE_SCAN="BONE_SCAN"
class DiagnosisCandidateStatus(str, Enum):
    PROPOSED="PROPOSED"; UNDER_EVALUATION="UNDER_EVALUATION"; RULED_OUT="RULED_OUT"
class MedicationStatus(str, Enum):
    ACTIVE="ACTIVE"; INACTIVE="INACTIVE"; UNKNOWN="UNKNOWN"
class MedicalHistoryCategory(str, Enum):
    PREVIOUS_SURGERY="PREVIOUS_SURGERY"; PREVIOUS_FRACTURE="PREVIOUS_FRACTURE"; PREVIOUS_INFECTION="PREVIOUS_INFECTION"
    AUTOIMMUNE_DISEASE="AUTOIMMUNE_DISEASE"; DIABETES="DIABETES"; CARDIOVASCULAR_DISEASE="CARDIOVASCULAR_DISEASE"
    NEUROLOGIC_DISEASE="NEUROLOGIC_DISEASE"; CANCER="CANCER"; CHRONIC_PAIN="CHRONIC_PAIN"


def _required(value: str, name: str) -> None:
    if not isinstance(value,str) or not value.strip(): raise PatientContextInvariantError(f"{name} is required")


@dataclass(frozen=True)
class Traceable:
    entity_id: str
    source: str
    author: str
    recorded_at: datetime
    confidence: float
    provenance: str
    def __post_init__(self):
        for value,name in ((self.entity_id,"entity_id"),(self.source,"source"),(self.author,"author"),(self.provenance,"provenance")): _required(value,name)
        if self.recorded_at.tzinfo is None: raise PatientContextInvariantError("recorded_at must be timezone-aware")
        if not 0 <= self.confidence <= 1: raise PatientContextInvariantError("confidence must be between 0 and 1")


@dataclass(frozen=True)
class ClinicalEvent(Traceable):
    timeline_id: str
    occurred_at: datetime
    def __post_init__(self):
        super().__post_init__();_required(self.timeline_id,"timeline_id")
        if self.occurred_at.tzinfo is None: raise PatientContextInvariantError("occurred_at must be timezone-aware")


@dataclass(frozen=True)
class PatientIdentity(Traceable):
    patient_id: str
    def __post_init__(self):
        super().__post_init__();_required(self.patient_id,"patient_id")
        if not re.fullmatch(r"pt_[0-9a-f]{64}",self.patient_id): raise PatientContextInvariantError("patient_id must be a canonical pseudonymous identifier")

@dataclass(frozen=True)
class RetentionMetadata:
    policy_id: str; retention_start: datetime; review_at: datetime
    archival_eligible_at: Optional[datetime]=None; deletion_eligible_at: Optional[datetime]=None
    def __post_init__(self):
        _required(self.policy_id,"retention policy_id")
        if any(item and item.tzinfo is None for item in (self.retention_start,self.review_at,self.archival_eligible_at,self.deletion_eligible_at)): raise PatientContextInvariantError("retention timestamps must be timezone-aware")

@dataclass(frozen=True)
class ClinicalProblem(ClinicalEvent):
    name: str; status: str; onset_date: Optional[date]=None
@dataclass(frozen=True)
class DiagnosisCandidate(ClinicalEvent):
    label: str; status: DiagnosisCandidateStatus; basis_references: tuple[str,...]=()
@dataclass(frozen=True)
class ClinicalFinding(ClinicalEvent):
    finding: str; body_site: Optional[str]=None; laterality: Laterality=Laterality.NOT_APPLICABLE
@dataclass(frozen=True)
class Comorbidity(ClinicalEvent):
    name: str; status: str
@dataclass(frozen=True)
class MedicalHistoryItem(ClinicalEvent):
    category: MedicalHistoryCategory; description: str; active: Optional[bool]=None
@dataclass(frozen=True)
class MedicationClass(ClinicalEvent):
    name: str
@dataclass(frozen=True)
class Medication(ClinicalEvent):
    name: str; medication_class_id: Optional[str]=None; dose: Optional[str]=None; route: Optional[str]=None; frequency: Optional[str]=None; status: MedicationStatus=MedicationStatus.UNKNOWN
@dataclass(frozen=True)
class Allergy(ClinicalEvent):
    substance: str; reaction: Optional[str]=None; severity: Optional[str]=None
@dataclass(frozen=True)
class ProcedureHistory(ClinicalEvent):
    procedure: str; body_site: Optional[str]=None; laterality: Laterality=Laterality.NOT_APPLICABLE
@dataclass(frozen=True)
class ImplantHistory(ClinicalEvent):
    implant: str; body_site: str; laterality: Laterality; manufacturer: Optional[str]=None; model: Optional[str]=None
@dataclass(frozen=True)
class LaboratoryResult(ClinicalEvent):
    test_name: str; value: str; unit: Optional[str]=None; reference_range: Optional[str]=None; specimen: Optional[str]=None
@dataclass(frozen=True)
class ImagingStudy(ClinicalEvent):
    modality: ImagingModality; body_site: str; findings: tuple[str,...]; report_reference: str
@dataclass(frozen=True)
class VitalSigns(ClinicalEvent):
    heart_rate_bpm: Optional[float]=None; systolic_bp_mmhg: Optional[float]=None; diastolic_bp_mmhg: Optional[float]=None; respiratory_rate_bpm: Optional[float]=None; temperature_c: Optional[float]=None; oxygen_saturation_percent: Optional[float]=None
@dataclass(frozen=True)
class FunctionalStatus(ClinicalEvent):
    description: str; scale: Optional[str]=None; score: Optional[str]=None
@dataclass(frozen=True)
class PainAssessment(ClinicalEvent):
    location: str; intensity: Optional[float]=None; scale_maximum: Optional[float]=None; character: tuple[str,...]=(); aggravating_factors: tuple[str,...]=(); relieving_factors: tuple[str,...]=()
@dataclass(frozen=True)
class RiskFactor(ClinicalEvent):
    name: str; present: Optional[bool]=None
@dataclass(frozen=True)
class LifestyleFactor(ClinicalEvent):
    category: str; description: str
@dataclass(frozen=True)
class Occupation(ClinicalEvent):
    title: str; physical_demand: Optional[str]=None
@dataclass(frozen=True)
class SportsActivity(ClinicalEvent):
    sport: str; level: Optional[str]=None; frequency: Optional[str]=None
@dataclass(frozen=True)
class FollowUpPlan(ClinicalEvent):
    plan: str; target_date: Optional[date]=None
@dataclass(frozen=True)
class Encounter(ClinicalEvent):
    encounter_type: EncounterType; location: Optional[str]=None; clinician: Optional[str]=None
@dataclass(frozen=True)
class ClinicalNoteReference(ClinicalEvent):
    note_type: str; reference: str


@dataclass(frozen=True)
class OrthopedicContext(ClinicalEvent):
    affected_joint: str; laterality: Laterality; alignment: Optional[str]=None
    range_of_motion: tuple[str,...]=(); instability_tests: tuple[str,...]=(); special_tests: tuple[str,...]=()
    previous_procedure_ids: tuple[str,...]=(); implant_ids: tuple[str,...]=(); sports_level: Optional[str]=None; occupation_demand: Optional[str]=None


@dataclass(frozen=True)
class CurrentCondition(ClinicalEvent):
    symptoms: tuple[str,...]; duration: Optional[str]=None; functional_limitations: tuple[str,...]=()
    instability: tuple[str,...]=(); mechanical_symptoms: tuple[str,...]=(); neurologic_symptoms: tuple[str,...]=(); inflammatory_symptoms: tuple[str,...]=()


@dataclass(frozen=True)
class TimelineEntry(ClinicalEvent):
    event_type: EncounterType; reference_type: str; reference_id: str; summary: str
    def __post_init__(self):
        super().__post_init__();_required(self.reference_type,"reference_type");_required(self.reference_id,"reference_id")


@dataclass(frozen=True)
class ClinicalTimeline(Traceable):
    timeline_id: str; patient_id: str; entries: tuple[TimelineEntry,...]=()
    def __post_init__(self):
        super().__post_init__();_required(self.timeline_id,"timeline_id");_required(self.patient_id,"patient_id")
        if len({item.entity_id for item in self.entries}) != len(self.entries): raise PatientContextInvariantError("timeline entries must be unique")
        if any(item.timeline_id != self.timeline_id for item in self.entries): raise PatientContextInvariantError("every clinical event must belong to this timeline")
        if tuple(sorted(self.entries,key=lambda item:(item.occurred_at,item.entity_id))) != self.entries: raise PatientContextInvariantError("timeline entries must be chronological")


@dataclass(frozen=True)
class PatientContext(Traceable):
    context_id: str; patient_identity: PatientIdentity; version: int; previous_context_id: Optional[str]
    effective_at: datetime; timeline: ClinicalTimeline; retention: RetentionMetadata
    age_years: Optional[int]=None; sex: Sex=Sex.NOT_REPORTED; weight_kg: Optional[float]=None; height_cm: Optional[float]=None; bmi: Optional[float]=None
    dominant_side: Optional[Laterality]=None; athlete_status: Optional[bool]=None; smoking: Optional[str]=None; alcohol: Optional[str]=None
    physical_activity: Optional[str]=None; pregnancy: Optional[str]=None; performance_status: Optional[str]=None
    clinical_problems: tuple[ClinicalProblem,...]=(); diagnosis_candidates: tuple[DiagnosisCandidate,...]=(); findings: tuple[ClinicalFinding,...]=()
    comorbidities: tuple[Comorbidity,...]=(); medical_history_items: tuple[MedicalHistoryItem,...]=(); medication_classes: tuple[MedicationClass,...]=(); medications: tuple[Medication,...]=(); allergies: tuple[Allergy,...]=()
    procedures: tuple[ProcedureHistory,...]=(); implants: tuple[ImplantHistory,...]=(); laboratory_results: tuple[LaboratoryResult,...]=(); imaging_studies: tuple[ImagingStudy,...]=()
    vital_signs: tuple[VitalSigns,...]=(); functional_statuses: tuple[FunctionalStatus,...]=(); pain_assessments: tuple[PainAssessment,...]=()
    risk_factors: tuple[RiskFactor,...]=(); lifestyle_factors: tuple[LifestyleFactor,...]=(); occupations: tuple[Occupation,...]=(); sports_activities: tuple[SportsActivity,...]=()
    follow_up_plans: tuple[FollowUpPlan,...]=(); encounters: tuple[Encounter,...]=(); clinical_note_references: tuple[ClinicalNoteReference,...]=()
    current_conditions: tuple[CurrentCondition,...]=(); orthopedic_contexts: tuple[OrthopedicContext,...]=()
    def __post_init__(self):
        super().__post_init__();_required(self.context_id,"context_id")
        if self.version < 1: raise PatientContextInvariantError("version must be positive")
        if self.version == 1 and self.previous_context_id is not None: raise PatientContextInvariantError("first version cannot have a predecessor")
        if self.version > 1 and not self.previous_context_id: raise PatientContextInvariantError("later versions require a predecessor")
        if self.effective_at.tzinfo is None: raise PatientContextInvariantError("effective_at must be timezone-aware")
        if self.timeline.patient_id != self.patient_identity.patient_id: raise PatientContextInvariantError("timeline and identity patient mismatch")
        if self.age_years is not None and not 0 <= self.age_years <= 130: raise PatientContextInvariantError("age is outside representable range")
        if self.weight_kg is not None and self.weight_kg <= 0: raise PatientContextInvariantError("weight must be positive")
        if self.height_cm is not None and self.height_cm <= 0: raise PatientContextInvariantError("height must be positive")
        if self.bmi is not None and self.bmi <= 0: raise PatientContextInvariantError("BMI must be positive")
        events=(self.clinical_problems+self.diagnosis_candidates+self.findings+self.comorbidities+self.medical_history_items+self.medication_classes+self.medications+self.allergies+self.procedures+self.implants+self.laboratory_results+self.imaging_studies+self.vital_signs+self.functional_statuses+self.pain_assessments+self.risk_factors+self.lifestyle_factors+self.occupations+self.sports_activities+self.follow_up_plans+self.encounters+self.clinical_note_references+self.current_conditions+self.orthopedic_contexts)
        if any(item.timeline_id != self.timeline.timeline_id for item in events): raise PatientContextInvariantError("clinical objects must belong to the canonical timeline")
