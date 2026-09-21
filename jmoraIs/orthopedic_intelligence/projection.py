from __future__ import annotations
from jmoraIs.clinical_state.domain import ClinicalReviewStatus,PatientClinicalState
from jmoraIs.terminology.domain import CodeSystem,MappingOutcome,TerminologyStatus
from .domain import *

class OrthopedicStateProjectionService:
    POLICY="MIP-07-PROJECTION-1"
    def __init__(self,terminology):self._terminology=terminology
    def project(self,state:PatientClinicalState,terminology_version:str)->GovernedOrthopedicStateView:
        if not isinstance(state,PatientClinicalState):raise OrthopedicBoundaryError("persisted PatientClinicalState is required")
        findings=[];stability=[];imaging=[];surgeries=[];implants=[]
        for item in state.orthopedic:
            joint=self._joint(item.joint,terminology_version);side=self._side(item.laterality,terminology_version)
            for term in item.mechanical_symptoms+item.rom+((item.alignment,) if item.alignment else ()):
                concept=self._concept(term,terminology_version);category=self._category(term,concept)
                findings.append(OrthopedicFindingReference(f"{item.reference_id}:{concept.canonical_id}",concept.canonical_id,joint,side,category,"clinical-state",1.0,item.provenance,"OBSERVED"))
            for term in item.instability:
                concept=self._concept(term,terminology_version);stability.append(StabilityFindingReference(f"{item.reference_id}:stability:{concept.canonical_id}",concept.canonical_id,joint,side,term,"clinical-state",1.0,item.provenance,"OBSERVED"))
            for ref in item.imaging_references:
                source=next((x for x in state.imaging if x.reference_id==ref),None)
                if source:
                    for term in source.finding_references:
                        concept=self._concept(term,terminology_version);imaging.append(ImagingFindingReference(source.reference_id,concept.canonical_id,source.modality,joint,side,source.source,source.provenance))
            for ref in item.previous_surgery_references:
                source=next((x for x in state.procedures if x.reference_id==ref),None)
                if source:
                    concept=self._concept(source.normalized_term or source.source_term,terminology_version);surgeries.append(SurgicalHistoryReference(ref,concept.canonical_id,joint,side,source.recorded_at,None,None,source.provenance))
            for ref in item.implant_references:
                source=next((x for x in state.implants if x.reference_id==ref),None)
                if source:
                    concept=self._concept(source.normalized_term or source.source_term,terminology_version);implants.append(ImplantStateReference(ref,concept.canonical_id,joint,side,source.recorded_at,None,source.provenance))
        functional=tuple(FunctionalReference(x.reference_id,x.gait,x.adls,x.work_limitations,x.sports,(),x.mobility,None,x.validated_score,x.provenance) for x in state.functional)
        flags=tuple(sorted({x.flag_type.value for x in state.quality_flags}|({"REVIEW_REQUIRED"} if state.review_status is ClinicalReviewStatus.REVIEW_REQUIRED else set())))
        return GovernedOrthopedicStateView(state.state_id,state.state_version,terminology_version,tuple(findings),tuple(stability),tuple(imaging),functional,tuple(surgeries),tuple(implants),flags,state.provenance_references,state.pseudonymous_patient_id,self.POLICY,state.as_of,state.state_version,state.previous_state_id)
    def _concept(self,term,version):
        mapped=self._terminology.resolve_concepts(term,CodeSystem.ORTHOPEDIC,version,actor_id="orthopedic-projection")
        if mapped.outcome is not MappingOutcome.MAPPED:raise OrthopedicBoundaryError("orthopedic terminology requires governed unambiguous mapping")
        concept=mapped.candidates[0]
        if concept.status is not TerminologyStatus.ACTIVE:raise OrthopedicBoundaryError("orthopedic terminology is not active")
        return concept
    def _joint(self,term,version):self._concept(term,version);return AnatomicalScope(term.upper())
    def _side(self,term,version):self._concept(term,version);return OrthopedicLaterality(term.upper())
    @staticmethod
    def _category(term,concept):
        value=term.upper().replace(" ","_")
        return FindingCategory.__members__.get(value,FindingCategory.FUNCTIONAL_LIMITATION)
