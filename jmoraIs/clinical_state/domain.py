from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

class ClinicalStateError(RuntimeError): pass
class ClinicalStateVersionConflict(ClinicalStateError): pass
class InvalidProblemTransition(ClinicalStateError): pass

class ProblemLifecycle(str,Enum):
    ACTIVE="ACTIVE";RESOLVED="RESOLVED";INACTIVE="INACTIVE";HISTORICAL="HISTORICAL";SUSPECTED="SUSPECTED";RULED_OUT="RULED_OUT"
class EpistemicStatus(str,Enum):
    CONFIRMED="CONFIRMED";REPORTED="REPORTED";OBSERVED="OBSERVED";SUSPECTED="SUSPECTED";INFERRED="INFERRED";UNKNOWN="UNKNOWN"
class ProblemTransitionType(str,Enum):
    OPEN="OPEN";CONFIRM="CONFIRM";RESOLVE="RESOLVE";REOPEN="REOPEN";RULE_OUT="RULE_OUT";MARK_HISTORICAL="MARK_HISTORICAL"
class DataQualityFlagType(str,Enum):
    MISSING_DATA="MISSING_DATA";CONFLICTING_DATA="CONFLICTING_DATA";STALE_DATA="STALE_DATA";UNVERIFIED_SOURCE="UNVERIFIED_SOURCE"
    TIMELINE_CONFLICT="TIMELINE_CONFLICT";UNIT_MISMATCH="UNIT_MISMATCH";LATERALITY_CONFLICT="LATERALITY_CONFLICT";DUPLICATE_EVENT="DUPLICATE_EVENT"
class ClinicalReviewStatus(str,Enum):
    AUTO_ASSEMBLED="AUTO_ASSEMBLED";REVIEW_REQUIRED="REVIEW_REQUIRED";REVIEWED="REVIEWED";CORRECTED="CORRECTED"
class MedicationLifecycle(str,Enum):
    STARTED="STARTED";ACTIVE="ACTIVE";SUSPENDED="SUSPENDED";DISCONTINUED="DISCONTINUED";UNKNOWN="UNKNOWN"
class ClinicalStateAuditType(str,Enum):
    STATE_CREATED="STATE_CREATED";PROBLEM_TRANSITION="PROBLEM_TRANSITION";CONFLICT_DETECTED="CONFLICT_DETECTED"
    REVIEW_REQUESTED="REVIEW_REQUESTED";CORRECTION="CORRECTION";SUPERSESSION="SUPERSESSION"

def _text(value,name):
    if not isinstance(value,str) or not value.strip(): raise ClinicalStateError(f"{name} is required")
def _aware(value,name):
    if value.tzinfo is None: raise ClinicalStateError(f"{name} must be timezone-aware")

@dataclass(frozen=True)
class StatementReference:
    reference_id:str;source_term:str;normalized_term:Optional[str];epistemic_status:EpistemicStatus
    source:str;source_event_id:str;recorded_at:datetime;provenance:str
    def __post_init__(self):
        for value,name in ((self.reference_id,"reference_id"),(self.source_term,"source_term"),(self.source,"source"),(self.source_event_id,"source_event_id"),(self.provenance,"provenance")): _text(value,name)
        _aware(self.recorded_at,"recorded_at")

@dataclass(frozen=True)
class ClinicalProblemRecord(StatementReference):
    lifecycle:ProblemLifecycle

@dataclass(frozen=True)
class ProblemTransition:
    transition_id:str;problem_id:str;transition:ProblemTransitionType;source_event_id:str;actor_id:str
    occurred_at:datetime;rationale:str;provenance:str;prior_state:Optional[ProblemLifecycle];resulting_state:ProblemLifecycle
    def __post_init__(self):
        for value,name in ((self.transition_id,"transition_id"),(self.problem_id,"problem_id"),(self.source_event_id,"source_event_id"),(self.actor_id,"actor_id"),(self.rationale,"rationale"),(self.provenance,"provenance")): _text(value,name)
        _aware(self.occurred_at,"occurred_at")

@dataclass(frozen=True)
class DataQualityFlag:
    flag_type:DataQualityFlagType;references:tuple[str,...];detail:str;review_required:bool=True

@dataclass(frozen=True)
class MedicationState(StatementReference):
    lifecycle:MedicationLifecycle;dose:Optional[str]=None;route:Optional[str]=None;start_at:Optional[datetime]=None;end_at:Optional[datetime]=None

@dataclass(frozen=True)
class ImagingState:
    reference_id:str;modality:str;site:str;laterality:str;finding_references:tuple[str,...];performed_at:datetime;source:str;provenance:str

@dataclass(frozen=True)
class LaboratoryState:
    reference_id:str;test:str;value:str;unit:Optional[str];supplied_reference_range:Optional[str];collected_at:datetime;provenance:str

@dataclass(frozen=True)
class FunctionalState:
    reference_id:str;description:str;gait:Optional[str];mobility:Optional[str];adls:tuple[str,...];sports:tuple[str,...]
    work_limitations:tuple[str,...];validated_score:Optional[str];pain_score:Optional[str];recorded_at:datetime;provenance:str

@dataclass(frozen=True)
class OrthopedicState:
    reference_id:str;anatomical_region:Optional[str];joint:str;laterality:str;rom:tuple[str,...];alignment:Optional[str]
    instability:tuple[str,...];mechanical_symptoms:tuple[str,...];weight_bearing_status:Optional[str]
    functional_limitations:tuple[str,...];sport_demand:Optional[str];occupational_demand:Optional[str]
    previous_surgery_references:tuple[str,...];implant_references:tuple[str,...];imaging_references:tuple[str,...];provenance:str

@dataclass(frozen=True)
class PatientClinicalState:
    state_id:str;pseudonymous_patient_id:str;patient_context_id:str;patient_context_version:int
    state_version:int;previous_state_id:Optional[str];as_of:datetime;review_status:ClinicalReviewStatus
    problems:tuple[ClinicalProblemRecord,...]=();symptoms:tuple[StatementReference,...]=();findings:tuple[StatementReference,...]=()
    medications:tuple[MedicationState,...]=();allergies:tuple[StatementReference,...]=();procedures:tuple[StatementReference,...]=()
    implants:tuple[StatementReference,...]=();laboratory:tuple[LaboratoryState,...]=();imaging:tuple[ImagingState,...]=()
    functional:tuple[FunctionalState,...]=();pain:tuple[StatementReference,...]=();risk_factors:tuple[StatementReference,...]=()
    orthopedic:tuple[OrthopedicState,...]=();quality_flags:tuple[DataQualityFlag,...]=();problem_transitions:tuple[ProblemTransition,...]=()
    provenance_references:tuple[str,...]=()
    def __post_init__(self):
        for value,name in ((self.state_id,"state_id"),(self.pseudonymous_patient_id,"pseudonymous_patient_id"),(self.patient_context_id,"patient_context_id")): _text(value,name)
        _aware(self.as_of,"as_of")
        if self.state_version<1 or self.patient_context_version<1: raise ClinicalStateError("versions must be positive")
        if self.state_version==1 and self.previous_state_id is not None: raise ClinicalStateError("genesis state cannot have predecessor")
        if self.state_version>1 and not self.previous_state_id: raise ClinicalStateError("later state requires predecessor")
        if not self.provenance_references: raise ClinicalStateError("state provenance is required")
        if self.quality_flags and self.review_status is ClinicalReviewStatus.AUTO_ASSEMBLED: raise ClinicalStateError("quality conflicts require review")

@dataclass(frozen=True)
class ClinicalStateAuditEvent:
    event_id:str;patient_id:str;state_id:str;event_type:ClinicalStateAuditType;occurred_at:datetime
    actor_id:str;source_event_id:str;provenance:str;detail_code:str
