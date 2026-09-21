from dataclasses import FrozenInstanceError,replace
from datetime import timedelta
import pytest

from jmoraIs.clinical_state import *
from jmoraIs.patient_context.domain import *
from tests.test_patient_context_domain import NOW,EVENT,context

def rich_context(identifier="context-state-1",version=1,previous=None,*,effective=NOW,changes=None):
    problem=ClinicalProblem(entity_id="problem-active",name="Knee pain",status="active",source="patient-report",author="patient",recorded_at=effective,confidence=1,provenance="questionnaire:1",timeline_id="timeline-1",occurred_at=effective)
    candidate=DiagnosisCandidate(entity_id="problem-suspected",label="Source candidate",status=DiagnosisCandidateStatus.UNDER_EVALUATION,**{**EVENT,"recorded_at":effective,"occurred_at":effective})
    finding=ClinicalFinding(entity_id="finding-1",finding="Limited motion",body_site="knee",laterality=Laterality.LEFT,**{**EVENT,"recorded_at":effective,"occurred_at":effective})
    med=Medication(entity_id="med-1",name="Recorded medication",dose=None,route=None,status=MedicationStatus.ACTIVE,**{**EVENT,"recorded_at":effective,"occurred_at":effective})
    lab=LaboratoryResult(entity_id="lab-1",test_name="CRP",value="5",unit="mg/L",reference_range="0-5",**{**EVENT,"recorded_at":effective,"occurred_at":effective})
    image=ImagingStudy(entity_id="image-1",modality=ImagingModality.MRI,body_site="knee",findings=("supplied finding",),report_reference="report:1",**{**EVENT,"recorded_at":effective,"occurred_at":effective})
    function=FunctionalStatus(entity_id="function-1",description="Independent gait",scale="score",score="8",**{**EVENT,"recorded_at":effective,"occurred_at":effective})
    pain=PainAssessment(entity_id="pain-1",location="knee",intensity=5,scale_maximum=10,**{**EVENT,"recorded_at":effective,"occurred_at":effective})
    risk=RiskFactor(entity_id="risk-1",name="Recorded risk",present=True,**{**EVENT,"recorded_at":effective,"occurred_at":effective})
    current=CurrentCondition(entity_id="condition-1",symptoms=("pain",),functional_limitations=("stairs",),mechanical_symptoms=("locking",),**{**EVENT,"recorded_at":effective,"occurred_at":effective})
    ortho=OrthopedicContext(entity_id="ortho-1",affected_joint="knee",laterality=Laterality.LEFT,range_of_motion=("0-110",),alignment="varus",instability_tests=("documented",),sports_level="recreational",occupation_demand="high",previous_procedure_ids=(),implant_ids=(),**{**EVENT,"recorded_at":effective,"occurred_at":effective})
    values=dict(clinical_problems=(problem,),diagnosis_candidates=(candidate,),findings=(finding,),medications=(med,),laboratory_results=(lab,),imaging_studies=(image,),functional_statuses=(function,),pain_assessments=(pain,),risk_factors=(risk,),current_conditions=(current,),orthopedic_contexts=(ortho,),effective_at=effective)
    values.update(changes or {})
    return context(identifier,version,previous,**values)

def service(contexts,*,clock=lambda:NOW,stale_after=timedelta(days=365)):
    query=AuthorizedPatientContextQueryAdapter(lambda patient:contexts)
    states=InMemoryClinicalStateRepository();audit=InMemoryClinicalStateAuditAdapter()
    normalizer=DeterministicClinicalNormalizer((("problem","Knee pain","knee pain"),("medication","Recorded medication","recorded medication")))
    return PatientClinicalStateService(query,states,audit,normalizer,clock=clock,stale_after=stale_after),states,audit

def test_current_state_is_immutable_reference_based_and_preserves_epistemic_status():
    app,_,_=service((rich_context(),));state=app.build_current_state(state_patient:=rich_context().patient_identity.patient_id)
    assert state.patient_context_version==1 and state.review_status is ClinicalReviewStatus.AUTO_ASSEMBLED
    assert {item.lifecycle for item in state.problems}=={ProblemLifecycle.ACTIVE,ProblemLifecycle.SUSPECTED}
    assert state.problems[0].epistemic_status is EpistemicStatus.REPORTED
    assert state.problems[1].epistemic_status is EpistemicStatus.SUSPECTED
    assert state.medications[0].dose is None and state.medications[0].route is None
    assert state.imaging[0].finding_references==("supplied finding",) and state.laboratory[0].value=="5"
    assert state.functional[0].validated_score=="8" and state.orthopedic[0].mechanical_symptoms==("locking",)
    with pytest.raises(FrozenInstanceError):state.review_status=ClinicalReviewStatus.REVIEWED

def test_historical_and_current_reconstruction_use_context_timestamp_and_never_mutate():
    first=rich_context(effective=NOW-timedelta(days=2));second=rich_context("context-state-2",2,first.context_id,effective=NOW)
    app,states,_=service((first,second))
    historical=app.build_historical_state(first.patient_identity.patient_id,NOW-timedelta(days=1))
    current=app.build_current_state(first.patient_identity.patient_id)
    assert historical.patient_context_id==first.context_id and current.previous_state_id==historical.state_id
    assert states.at(first.patient_identity.patient_id,NOW-timedelta(days=1))==historical

def test_problem_transitions_are_append_only_and_confirmation_is_explicit():
    ctx=rich_context();app,states,audit=service((ctx,));first=app.build_current_state(ctx.patient_identity.patient_id)
    confirmed=app.transition_problem(ctx.patient_identity.patient_id,"problem-suspected",ProblemTransitionType.CONFIRM,
      source_event_id="physician-review:1",actor_id="physician-1",occurred_at=NOW,rationale="explicit source review",provenance="review:1")
    problem=next(item for item in confirmed.problems if item.reference_id=="problem-suspected")
    assert problem.lifecycle is ProblemLifecycle.ACTIVE and problem.epistemic_status is EpistemicStatus.CONFIRMED
    resolved=app.transition_problem(ctx.patient_identity.patient_id,"problem-active",ProblemTransitionType.RESOLVE,
      source_event_id="followup:1",actor_id="physician-1",occurred_at=NOW,rationale="recorded resolved",provenance="followup:1")
    reopened=app.transition_problem(ctx.patient_identity.patient_id,"problem-active",ProblemTransitionType.REOPEN,
      source_event_id="followup:2",actor_id="physician-1",occurred_at=NOW,rationale="recorded recurrence",provenance="followup:2")
    assert len(states.history(ctx.patient_identity.patient_id))==4 and reopened.problem_transitions[-1].prior_state is ProblemLifecycle.RESOLVED
    assert any(item.event_type is ClinicalStateAuditType.PROBLEM_TRANSITION for item in audit.history(ctx.patient_identity.patient_id))
    with pytest.raises(InvalidProblemTransition):app.transition_problem(ctx.patient_identity.patient_id,"problem-suspected",ProblemTransitionType.REOPEN,source_event_id="x",actor_id="x",occurred_at=NOW,rationale="x",provenance="x")

def test_rule_out_remains_historical_and_never_becomes_confirmed_automatically():
    ctx=rich_context();app,_,_=service((ctx,));app.build_current_state(ctx.patient_identity.patient_id)
    ruled=app.transition_problem(ctx.patient_identity.patient_id,"problem-suspected",ProblemTransitionType.RULE_OUT,
      source_event_id="review",actor_id="physician",occurred_at=NOW,rationale="explicitly ruled out",provenance="review")
    problem=next(item for item in ruled.problems if item.reference_id=="problem-suspected")
    assert problem.lifecycle is ProblemLifecycle.RULED_OUT and problem.epistemic_status is EpistemicStatus.SUSPECTED

def test_quality_conflicts_are_preserved_and_require_review():
    left=rich_context().orthopedic_contexts[0];right=replace(left,entity_id="ortho-2",laterality=Laterality.RIGHT)
    lab2=replace(rich_context().laboratory_results[0],entity_id="lab-2",unit="mmol/L")
    ctx=rich_context(changes={"orthopedic_contexts":(left,right),"laboratory_results":(rich_context().laboratory_results[0],lab2)})
    app,_,audit=service((ctx,));state=app.build_current_state(ctx.patient_identity.patient_id)
    kinds={item.flag_type for item in state.quality_flags}
    assert {DataQualityFlagType.LATERALITY_CONFLICT,DataQualityFlagType.UNIT_MISMATCH}<=kinds
    assert state.review_status is ClinicalReviewStatus.REVIEW_REQUIRED
    assert any(item.event_type is ClinicalStateAuditType.CONFLICT_DETECTED for item in audit.history(ctx.patient_identity.patient_id))

def test_stale_and_timeline_conflicts_are_not_silently_reconciled():
    old=NOW-timedelta(days=10);future=NOW+timedelta(days=1)
    stale=replace(rich_context().findings[0],recorded_at=old,occurred_at=future)
    ctx=rich_context(changes={"findings":(stale,)})
    app,_,_=service((ctx,),stale_after=timedelta(days=1));state=app.build_current_state(ctx.patient_identity.patient_id)
    assert {DataQualityFlagType.STALE_DATA,DataQualityFlagType.TIMELINE_CONFLICT}<={item.flag_type for item in state.quality_flags}

def test_review_and_correction_create_new_versions_with_audit():
    ctx=rich_context();app,states,audit=service((ctx,));initial=app.build_current_state(ctx.patient_identity.patient_id)
    requested=app.request_review(ctx.patient_identity.patient_id,actor_id="reviewer",source_event_id="request",provenance="request:1")
    reviewed=app.create_reviewed_version(ctx.patient_identity.patient_id,actor_id="physician",source_event_id="review",provenance="review:1")
    corrected=app.create_corrected_version(ctx.patient_identity.patient_id,replace(reviewed,quality_flags=()),actor_id="physician",source_event_id="correction",provenance="correction:1")
    assert [item.review_status for item in (initial,requested,reviewed,corrected)]==[ClinicalReviewStatus.AUTO_ASSEMBLED,ClinicalReviewStatus.REVIEW_REQUIRED,ClinicalReviewStatus.REVIEWED,ClinicalReviewStatus.CORRECTED]
    assert len(states.history(ctx.patient_identity.patient_id))==4
    assert audit.history(ctx.patient_identity.patient_id)[-1].event_type is ClinicalStateAuditType.CORRECTION
