from __future__ import annotations
from dataclasses import replace
from datetime import timedelta
from hashlib import sha256

from jmoraIs.patient_context.domain import DiagnosisCandidateStatus,Laterality,MedicationStatus
from .domain import *

class PatientClinicalStateService:
    """Deterministic state assembly only; contains no diagnostic or recommendation logic."""
    def __init__(self,contexts,states,audit,normalizer,*,clock,stale_after=timedelta(days=365)):
        self._contexts=contexts;self._states=states;self._audit=audit;self._normalizer=normalizer;self._clock=clock;self._stale_after=stale_after

    def build_current_state(self,patient_id): return self._build(self._contexts.current(patient_id))
    def build_historical_state(self,patient_id,as_of): return self._build(self._contexts.at(patient_id,as_of))
    def reconcile_new_context(self,patient_id): return self.build_current_state(patient_id)

    def _build(self,context):
        latest=self._states.latest(context.patient_identity.patient_id)
        if latest and latest.patient_context_id==context.context_id: return latest
        version=1 if latest is None else latest.state_version+1
        problems=[]
        for item in context.clinical_problems:
            lifecycle={"resolved":ProblemLifecycle.RESOLVED,"inactive":ProblemLifecycle.INACTIVE,"historical":ProblemLifecycle.HISTORICAL}.get(item.status.casefold(),ProblemLifecycle.ACTIVE)
            problems.append(ClinicalProblemRecord(item.entity_id,item.name,self._normalizer.normalize("problem",item.name),self._epistemic(item.source),item.source,item.entity_id,item.recorded_at,item.provenance,lifecycle))
        for item in context.diagnosis_candidates:
            lifecycle=ProblemLifecycle.RULED_OUT if item.status is DiagnosisCandidateStatus.RULED_OUT else ProblemLifecycle.SUSPECTED
            problems.append(ClinicalProblemRecord(item.entity_id,item.label,self._normalizer.normalize("problem",item.label),EpistemicStatus.SUSPECTED,item.source,item.entity_id,item.recorded_at,item.provenance,lifecycle))
        symptoms=tuple(StatementReference(f"{item.entity_id}:symptom:{index}",term,self._normalizer.normalize("symptom",term),self._epistemic(item.source),item.source,item.entity_id,item.recorded_at,item.provenance)
          for item in context.current_conditions for index,term in enumerate(item.symptoms))
        findings=tuple(self._statement(item,item.finding,"finding",EpistemicStatus.OBSERVED) for item in context.findings)
        medications=tuple(MedicationState(item.entity_id,item.name,self._normalizer.normalize("medication",item.name),self._epistemic(item.source),item.source,item.entity_id,item.recorded_at,item.provenance,
          {MedicationStatus.ACTIVE:MedicationLifecycle.ACTIVE,MedicationStatus.INACTIVE:MedicationLifecycle.DISCONTINUED}.get(item.status,MedicationLifecycle.UNKNOWN),item.dose,item.route,None,None) for item in context.medications)
        allergies=tuple(self._statement(item,item.substance,"allergy") for item in context.allergies)
        procedures=tuple(self._statement(item,item.procedure,"procedure") for item in context.procedures)
        implants=tuple(self._statement(item,item.implant,"implant") for item in context.implants)
        laboratory=tuple(LaboratoryState(item.entity_id,item.test_name,item.value,item.unit,item.reference_range,item.occurred_at,item.provenance) for item in context.laboratory_results)
        imaging=tuple(ImagingState(item.entity_id,item.modality.value,item.body_site,"UNKNOWN",item.findings,item.occurred_at,item.source,item.provenance) for item in context.imaging_studies)
        functional=tuple(FunctionalState(item.entity_id,item.description,None,None,(),(),(),item.score,None,item.occurred_at,item.provenance) for item in context.functional_statuses)
        pain=tuple(self._statement(item,item.location,"pain",EpistemicStatus.REPORTED) for item in context.pain_assessments)
        risks=tuple(self._statement(item,item.name,"risk") for item in context.risk_factors)
        orthopedic=tuple(OrthopedicState(item.entity_id,None,item.affected_joint,item.laterality.value,item.range_of_motion,item.alignment,item.instability_tests,
          tuple(term for condition in context.current_conditions for term in condition.mechanical_symptoms),None,
          tuple(term for condition in context.current_conditions for term in condition.functional_limitations),item.sports_level,item.occupation_demand,
          item.previous_procedure_ids,item.implant_ids,tuple(image.entity_id for image in context.imaging_studies if image.body_site.casefold()==item.affected_joint.casefold()),item.provenance) for item in context.orthopedic_contexts)
        flags=self._quality(context,tuple(problems))
        state_id=self._id(context.context_id,version,latest.state_id if latest else "genesis")
        provenance=tuple(sorted({context.provenance,*(item.provenance for item in problems),*(item.provenance for item in context.timeline.entries)}))
        state=PatientClinicalState(state_id,context.patient_identity.patient_id,context.context_id,context.version,version,latest.state_id if latest else None,
          context.effective_at,ClinicalReviewStatus.REVIEW_REQUIRED if flags else ClinicalReviewStatus.AUTO_ASSEMBLED,tuple(problems),symptoms,findings,
          medications,allergies,procedures,implants,laboratory,imaging,functional,pain,risks,orthopedic,flags,(),provenance)
        self._states.append(state);self._event(state,ClinicalStateAuditType.STATE_CREATED,"system",context.context_id,"STATE_ASSEMBLED")
        for flag in flags: self._event(state,ClinicalStateAuditType.CONFLICT_DETECTED,"system",context.context_id,flag.flag_type.value)
        if latest:self._event(latest,ClinicalStateAuditType.SUPERSESSION,"system",context.context_id,"NEW_CONTEXT_VERSION")
        return state

    def transition_problem(self,patient_id,problem_id,transition,*,source_event_id,actor_id,occurred_at,rationale,provenance):
        current=self._require(patient_id);problem=next((item for item in current.problems if item.reference_id==problem_id),None)
        if problem is None: raise InvalidProblemTransition("problem does not exist")
        target=self._transition_target(problem.lifecycle,transition)
        epistemic=EpistemicStatus.CONFIRMED if transition is ProblemTransitionType.CONFIRM else problem.epistemic_status
        changed=replace(problem,lifecycle=target,epistemic_status=epistemic)
        record=ProblemTransition(self._id(current.state_id,transition.value,str(current.state_version+1)),problem_id,transition,source_event_id,actor_id,occurred_at,rationale,provenance,problem.lifecycle,target)
        state=self._next(current,problems=tuple(changed if item.reference_id==problem_id else item for item in current.problems),problem_transitions=current.problem_transitions+(record,))
        self._states.append(state);self._event(state,ClinicalStateAuditType.PROBLEM_TRANSITION,actor_id,source_event_id,transition.value);return state

    def request_review(self,patient_id,*,actor_id,source_event_id,provenance):
        current=self._require(patient_id);state=self._next(current,review_status=ClinicalReviewStatus.REVIEW_REQUIRED)
        self._states.append(state);self._event(state,ClinicalStateAuditType.REVIEW_REQUESTED,actor_id,source_event_id,"REVIEW_REQUIRED",provenance);return state
    def create_reviewed_version(self,patient_id,*,actor_id,source_event_id,provenance):
        current=self._require(patient_id);state=self._next(current,review_status=ClinicalReviewStatus.REVIEWED,provenance_references=current.provenance_references+(provenance,))
        self._states.append(state);self._event(state,ClinicalStateAuditType.CORRECTION,actor_id,source_event_id,"REVIEWED",provenance);return state
    def create_corrected_version(self,patient_id,corrected,*,actor_id,source_event_id,provenance):
        current=self._require(patient_id)
        if corrected.pseudonymous_patient_id!=patient_id: raise ClinicalStateError("correction patient mismatch")
        state=replace(corrected,state_id=self._id(current.state_id,"corrected",str(current.state_version+1)),state_version=current.state_version+1,
          previous_state_id=current.state_id,review_status=ClinicalReviewStatus.CORRECTED,provenance_references=corrected.provenance_references+(provenance,))
        self._states.append(state);self._event(state,ClinicalStateAuditType.CORRECTION,actor_id,source_event_id,"CORRECTED",provenance);return state

    def _next(self,current,**changes):
        return replace(current,state_id=self._id(current.state_id,"next",str(current.state_version+1)),state_version=current.state_version+1,previous_state_id=current.state_id,as_of=self._clock(),**changes)
    def _require(self,patient_id):
        state=self._states.latest(patient_id)
        if state is None: raise ClinicalStateError("clinical state does not exist")
        return state
    def _statement(self,item,term,category,epistemic=None): return StatementReference(item.entity_id,term,self._normalizer.normalize(category,term),epistemic or self._epistemic(item.source),item.source,item.entity_id,item.recorded_at,item.provenance)
    @staticmethod
    def _epistemic(source): return EpistemicStatus.REPORTED if "patient" in source.casefold() else EpistemicStatus.OBSERVED
    @staticmethod
    def _id(*parts): return "cs_"+sha256("|".join(str(part) for part in parts).encode()).hexdigest()
    def _event(self,state,kind,actor,source,code,provenance=None):
        self._audit.append(ClinicalStateAuditEvent(self._id(state.state_id,kind.value,code),state.pseudonymous_patient_id,state.state_id,kind,self._clock(),actor,source,provenance or state.provenance_references[0],code))
    @staticmethod
    def _transition_target(prior,transition):
        allowed={ProblemTransitionType.OPEN:({ProblemLifecycle.INACTIVE,ProblemLifecycle.HISTORICAL},ProblemLifecycle.ACTIVE),
          ProblemTransitionType.CONFIRM:({ProblemLifecycle.ACTIVE,ProblemLifecycle.SUSPECTED},ProblemLifecycle.ACTIVE),
          ProblemTransitionType.RESOLVE:({ProblemLifecycle.ACTIVE},ProblemLifecycle.RESOLVED),
          ProblemTransitionType.REOPEN:({ProblemLifecycle.RESOLVED,ProblemLifecycle.INACTIVE},ProblemLifecycle.ACTIVE),
          ProblemTransitionType.RULE_OUT:({ProblemLifecycle.SUSPECTED,ProblemLifecycle.ACTIVE},ProblemLifecycle.RULED_OUT),
          ProblemTransitionType.MARK_HISTORICAL:({ProblemLifecycle.RESOLVED,ProblemLifecycle.INACTIVE,ProblemLifecycle.RULED_OUT},ProblemLifecycle.HISTORICAL)}
        sources,target=allowed[transition]
        if prior not in sources: raise InvalidProblemTransition(f"{transition.value} is invalid from {prior.value}")
        return target
    def _quality(self,context,problems):
        flags=[];events=tuple(item for group in (context.findings,context.medications,context.laboratory_results,context.imaging_studies,context.orthopedic_contexts) for item in group)
        ids=[item.entity_id for item in events]
        if len(ids)!=len(set(ids)): flags.append(DataQualityFlag(DataQualityFlagType.DUPLICATE_EVENT,tuple(ids),"duplicate source event"))
        lateralities={item.affected_joint.casefold():set() for item in context.orthopedic_contexts}
        for item in context.orthopedic_contexts:lateralities[item.affected_joint.casefold()].add(item.laterality)
        if any(len(values)>1 for values in lateralities.values()): flags.append(DataQualityFlag(DataQualityFlagType.LATERALITY_CONFLICT,tuple(item.entity_id for item in context.orthopedic_contexts),"conflicting laterality"))
        units={item.test_name.casefold():set() for item in context.laboratory_results}
        for item in context.laboratory_results: units[item.test_name.casefold()].add(item.unit)
        if any(len(values)>1 for values in units.values()): flags.append(DataQualityFlag(DataQualityFlagType.UNIT_MISMATCH,tuple(item.entity_id for item in context.laboratory_results),"unit mismatch preserved"))
        stale=tuple(item.entity_id for item in events if context.effective_at-item.recorded_at>self._stale_after)
        if stale: flags.append(DataQualityFlag(DataQualityFlagType.STALE_DATA,stale,"supplied clinical data is stale"))
        if any(item.occurred_at>context.effective_at for item in events): flags.append(DataQualityFlag(DataQualityFlagType.TIMELINE_CONFLICT,tuple(item.entity_id for item in events if item.occurred_at>context.effective_at),"event occurs after context effective time"))
        grouped={}
        for item in problems:grouped.setdefault((item.normalized_term or item.source_term).casefold(),set()).add(item.lifecycle)
        if any(len(values)>1 for values in grouped.values()): flags.append(DataQualityFlag(DataQualityFlagType.CONFLICTING_DATA,tuple(item.reference_id for item in problems),"problem lifecycle conflict"))
        if not (problems or context.findings or context.current_conditions): flags.append(DataQualityFlag(DataQualityFlagType.MISSING_DATA,(context.context_id,),"no problem, symptom, or finding supplied"))
        return tuple(flags)
