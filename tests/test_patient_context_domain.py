from dataclasses import FrozenInstanceError, fields, is_dataclass, replace
from datetime import datetime, timezone
import pytest
from jmoraIs.patient_context.domain import *

NOW=datetime(2026,8,10,tzinfo=timezone.utc)
PATIENT_ID="pt_"+("a"*64)
TRACE={"source":"clinician-entered","author":"physician-1","recorded_at":NOW,"confidence":1.0,"provenance":"encounter:1"}
EVENT={**TRACE,"timeline_id":"timeline-1","occurred_at":NOW}

def identity(patient_id=PATIENT_ID): return PatientIdentity(entity_id=f"identity-{patient_id}",patient_id=patient_id,**TRACE)
def entry(identifier="entry-1",kind=EncounterType.CONSULTATION):
    return TimelineEntry(entity_id=identifier,event_type=kind,reference_type="Encounter",reference_id="encounter-1",summary="Recorded event",**EVENT)
def timeline(entries=None,patient_id=PATIENT_ID):
    return ClinicalTimeline(entity_id="timeline-record-1",timeline_id="timeline-1",patient_id=patient_id,entries=tuple(entries or (entry(),)),**TRACE)
def context(identifier="context-1",version=1,previous=None,entries=None,patient_id=PATIENT_ID,**changes):
    values=dict(entity_id=f"record-{identifier}",context_id=identifier,patient_identity=identity(patient_id),version=version,
      previous_context_id=previous,effective_at=NOW,timeline=timeline(entries,patient_id),
      retention=RetentionMetadata("clinical-7y",NOW,NOW.replace(year=2027)),age_years=45,sex=Sex.FEMALE,
      weight_kg=70,height_cm=170,bmi=24.2,dominant_side=Laterality.RIGHT,athlete_status=True,
      smoking="never",alcohol="none",physical_activity="regular",pregnancy="not reported",performance_status="independent",**TRACE)
    values.update(changes);return PatientContext(**values)

def test_patient_context_and_all_domain_entities_are_immutable():
    values=[identity(),entry(),timeline(),context(),
      ClinicalProblem(entity_id="problem",name="Chronic pain",status="active",**EVENT),
      DiagnosisCandidate(entity_id="candidate",label="Candidate only",status=DiagnosisCandidateStatus.UNDER_EVALUATION,**EVENT),
      ClinicalFinding(entity_id="finding",finding="Limited motion",body_site="knee",laterality=Laterality.LEFT,**EVENT),
      Comorbidity(entity_id="comorbidity",name="Diabetes",status="active",**EVENT),
      MedicalHistoryItem(entity_id="history",category=MedicalHistoryCategory.PREVIOUS_FRACTURE,description="Previous fracture documented",**EVENT),
      MedicationClass(entity_id="class",name="Analgesic",**EVENT),Medication(entity_id="med",name="Medication",**EVENT),
      Allergy(entity_id="allergy",substance="Latex",**EVENT),ProcedureHistory(entity_id="procedure",procedure="Arthroscopy",**EVENT),
      ImplantHistory(entity_id="implant",implant="Fixation device",body_site="knee",laterality=Laterality.LEFT,**EVENT),
      LaboratoryResult(entity_id="lab",test_name="Test",value="10",unit="mg/L",**EVENT),
      ImagingStudy(entity_id="image",modality=ImagingModality.MRI,body_site="knee",findings=("Reported finding",),report_reference="report:1",**EVENT),
      VitalSigns(entity_id="vitals",heart_rate_bpm=70,**EVENT),FunctionalStatus(entity_id="function",description="Independent",**EVENT),
      PainAssessment(entity_id="pain",location="knee",intensity=5,scale_maximum=10,**EVENT),RiskFactor(entity_id="risk",name="Smoking",present=False,**EVENT),
      LifestyleFactor(entity_id="life",category="activity",description="regular",**EVENT),Occupation(entity_id="occupation",title="surgeon",physical_demand="standing",**EVENT),
      SportsActivity(entity_id="sport",sport="running",level="recreational",**EVENT),FollowUpPlan(entity_id="follow",plan="Review",**EVENT),
      Encounter(entity_id="encounter",encounter_type=EncounterType.CONSULTATION,**EVENT),ClinicalNoteReference(entity_id="note",note_type="consult",reference="note:1",**EVENT),
      CurrentCondition(entity_id="current",symptoms=("pain",),duration="2 weeks",mechanical_symptoms=("locking",),**EVENT),
      OrthopedicContext(entity_id="ortho",affected_joint="knee",laterality=Laterality.LEFT,range_of_motion=("0-120",),**EVENT)]
    for value in values:
        assert is_dataclass(value)
        assert {"source","author","recorded_at","confidence","provenance"} <= {item.name for item in fields(value)}
        with pytest.raises(FrozenInstanceError): value.source="changed"

def test_structured_laboratory_and_imaging_do_not_interpret_or_diagnose():
    lab=LaboratoryResult(entity_id="lab",test_name="CRP",value="12",unit="mg/L",reference_range="0-5",specimen="serum",**EVENT)
    image=ImagingStudy(entity_id="image",modality=ImagingModality.XRAY,body_site="knee",findings=("Joint-space narrowing described",),report_reference="report:2",**EVENT)
    assert lab.value=="12" and not hasattr(lab,"interpretation")
    assert image.findings and not hasattr(image,"diagnosis")

def test_orthopedic_and_current_condition_extensions_are_structured():
    condition=CurrentCondition(entity_id="condition",symptoms=("pain","swelling"),duration="three months",functional_limitations=("stairs",),instability=("giving way",),neurologic_symptoms=(),inflammatory_symptoms=("morning stiffness",),**EVENT)
    orthopedic=OrthopedicContext(entity_id="ortho",affected_joint="knee",laterality=Laterality.RIGHT,alignment="varus",range_of_motion=("extension 0","flexion 110"),instability_tests=("drawer documented",),special_tests=("test documented",),sports_level="competitive",occupation_demand="high",**EVENT)
    assert condition.mechanical_symptoms==() and orthopedic.laterality is Laterality.RIGHT

def test_traceability_and_patient_invariants_fail_closed():
    with pytest.raises(PatientContextInvariantError,match="source"): identity().__class__(entity_id="x",patient_id=PATIENT_ID,**{**TRACE,"source":""})
    with pytest.raises(PatientContextInvariantError,match="confidence"): PatientIdentity(entity_id="x",patient_id=PATIENT_ID,**{**TRACE,"confidence":1.1})
    with pytest.raises(PatientContextInvariantError,match="timezone"): PatientIdentity(entity_id="x",patient_id=PATIENT_ID,**{**TRACE,"recorded_at":datetime(2026,1,1)})
    with pytest.raises(PatientContextInvariantError,match="pseudonymous"): PatientIdentity(entity_id="x",patient_id="direct-reference",**TRACE)
    with pytest.raises(PatientContextInvariantError,match="predecessor"): context(version=2)

def test_every_clinical_object_must_belong_to_canonical_timeline():
    foreign=ClinicalFinding(entity_id="finding",finding="finding",timeline_id="other",occurred_at=NOW,**TRACE)
    with pytest.raises(PatientContextInvariantError,match="canonical timeline"): context(findings=(foreign,))
    with pytest.raises(PatientContextInvariantError,match="belong"): timeline((replace(entry(),timeline_id="other"),))

def test_timeline_requires_deterministic_chronological_order():
    earlier=replace(entry("early"),occurred_at=NOW.replace(hour=8));later=replace(entry("late"),occurred_at=NOW.replace(hour=9))
    assert timeline((earlier,later)).entries==(earlier,later)
    with pytest.raises(PatientContextInvariantError,match="chronological"): timeline((later,earlier))
