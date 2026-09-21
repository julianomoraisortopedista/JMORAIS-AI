from __future__ import annotations
from jmoraIs.clinical_state.domain import EpistemicStatus,PatientClinicalState
from .domain import DocumentBoundaryRejected,DocumentFactReference,FactEpistemicStatus,SourceType

class DocumentClinicalStateProjectionService:
    POLICY="MIP-08-CLINICAL-FACT-1"
    EPISTEMIC={EpistemicStatus.CONFIRMED:FactEpistemicStatus.FACT_CONFIRMED,EpistemicStatus.REPORTED:FactEpistemicStatus.FACT_REPORTED,EpistemicStatus.OBSERVED:FactEpistemicStatus.FACT_OBSERVED,EpistemicStatus.SUSPECTED:FactEpistemicStatus.FACT_SUSPECTED,EpistemicStatus.INFERRED:FactEpistemicStatus.FACT_INFERRED,EpistemicStatus.UNKNOWN:FactEpistemicStatus.FACT_UNKNOWN}
    def project(self,state):
        if not isinstance(state,PatientClinicalState):raise DocumentBoundaryRejected("persisted PatientClinicalState is required")
        flags=tuple(sorted(x.flag_type.value for x in state.quality_flags));review=state.review_status.value;facts=[]
        for category,items in (("problem",state.problems),("symptom",state.symptoms),("finding",state.findings),("medication",state.medications),("allergy",state.allergies),("procedure",state.procedures),("implant",state.implants),("pain",state.pain),("risk",state.risk_factors)):
            for item in items:facts.append(self._statement(state,item,category,flags,review))
        for item in state.laboratory:facts.append(self._fact(state,item.reference_id,f"laboratory: {item.test}",FactEpistemicStatus.FACT_OBSERVED,item.provenance,item.collected_at,(),flags,review,item.reference_id))
        for item in state.imaging:facts.append(self._fact(state,item.reference_id,f"imaging: {item.modality} {item.site}",FactEpistemicStatus.FACT_OBSERVED,item.provenance,item.performed_at,tuple(item.finding_references),flags,review,item.reference_id))
        for item in state.functional:facts.append(self._fact(state,item.reference_id,f"functional state: {item.description}",FactEpistemicStatus.FACT_REPORTED,item.provenance,item.recorded_at,(),flags,review,item.reference_id))
        for item in state.orthopedic:facts.append(self._fact(state,item.reference_id,f"orthopedic reference: {item.joint} {item.laterality}",FactEpistemicStatus.FACT_OBSERVED,item.provenance,state.as_of,(),flags,review,item.reference_id))
        return tuple(facts)
    def _statement(self,state,item,category,flags,review):
        term=item.normalized_term or item.source_term
        terminology=(item.normalized_term,) if item.normalized_term else ()
        return self._fact(state,item.reference_id,f"{category}: {term}",self.EPISTEMIC[item.epistemic_status],item.provenance,item.recorded_at,terminology,flags,review,item.source_event_id)
    def _fact(self,state,identifier,statement,epistemic,provenance,recorded,terminology,flags,review,original):
        return DocumentFactReference(identifier,statement,epistemic,SourceType.PATIENT_CLINICAL_STATE,state.state_id,str(state.state_version),tuple(terminology),tuple(sorted({provenance,*state.provenance_references})),self.POLICY,recorded,flags,review,original)
