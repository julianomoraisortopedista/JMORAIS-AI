from __future__ import annotations
from dataclasses import replace
from hashlib import sha256
from jmoraIs.appraisal.governed import GovernedEvidence
from jmoraIs.clinical.governed import GovernedClinicalRecommendation,GovernedRecommendationExplanation,HumanReviewStatus
from jmoraIs.guideline_engine.domain import GuidelineRecommendationSet,RecommendationReadiness
from jmoraIs.reasoning_input.domain import ClinicalReasoningInput,ReasoningReadiness
from jmoraIs.terminology.domain import ClinicalConcept,TerminologyStatus
from .domain import *

class OrthopedicIntelligenceService:
    POLICY="MIP-07.1";CONFIDENCE_POLICY="MIP-07-CONFIDENCE-1"
    MECHANICAL={FindingCategory.LOCKING,FindingCategory.CATCHING,FindingCategory.CREPITUS}
    def __init__(self,state,evidence,evidence_lifecycle,guidelines,terminology,repository,audit,review_service,*,clock,reasoning_inputs=None):
        self._state=state;self._evidence=evidence;self._evidence_lifecycle=evidence_lifecycle;self._guidelines=guidelines;self._terminology=terminology;self._repository=repository;self._audit=audit;self._review=review_service;self._clock=clock;self._reasoning_inputs=reasoning_inputs
    def generate(self,value,*,actor_id="orthopedic-engine",reasoning_input_reference=None):
        self._guard(value)
        if reasoning_input_reference is not None:
            if self._reasoning_inputs is None:raise OrthopedicBoundaryError("canonical Clinical Reasoning exact query port is required")
            try:exact=self._reasoning_inputs.get_exact(reasoning_input_reference)
            except Exception as exc:raise OrthopedicBoundaryError("Clinical Reasoning exact reference is invalid") from exc
            if exact!=value or (reasoning_input_reference.input_id,reasoning_input_reference.input_version)!=(value.input_id,value.input_version):raise OrthopedicBoundaryError("Clinical Reasoning exact reference mismatch")
        state=self._state.get(value.patient_clinical_state.reference_id)
        if not isinstance(state,GovernedOrthopedicStateView) or state.state_version!=value.patient_clinical_state.clinical_state_version or state.terminology_version!=value.terminology_version or not state.provenance_references:
            self._blocked(value,actor_id,"INVALID_GOVERNED_STATE");raise OrthopedicBoundaryError("governed clinical state reference is invalid")
        concept_ids={x.concept_id for x in state.findings}|{x.test_concept_id for x in state.stability_findings}|{x.finding_concept_id for x in state.imaging}|{x.procedure_concept_id for x in state.surgeries}|{x.implant_type_concept_id for x in state.implants}
        concepts={identifier:self._concept(identifier,value.terminology_version) for identifier in concept_ids}
        evidence=self._evidence_items(value);guidelines=self._guideline_set(value)
        keys=sorted({(x.joint,x.laterality) for x in state.findings+state.stability_findings+state.imaging+state.surgeries+state.implants},key=lambda x:(x[0].value,x[1].value))
        joints=tuple(self._joint(key,state,evidence,guidelines) for key in keys)
        flags=set(state.quality_flags)|{flag for joint in joints for flag in joint.quality_flags};laterality={joint:{x.laterality for x in state.findings if x.joint is joint and x.laterality not in {OrthopedicLaterality.UNKNOWN,OrthopedicLaterality.BILATERAL}} for joint in AnatomicalScope}
        if any(len(sides)>1 for sides in laterality.values()):flags.add("LATERALITY_CONFLICT")
        if not state.findings:readiness=AssessmentReadiness.INSUFFICIENT_DATA;flags.add("NO_ORTHOPEDIC_FINDINGS")
        elif "LATERALITY_CONFLICT" in flags or "CONFLICTING_DATA" in flags:readiness=AssessmentReadiness.CONFLICTING_DATA
        elif any("REVIEW_REQUIRED" in flag or "UNSUPPORTED_SEVERITY" in flag for flag in flags):readiness=AssessmentReadiness.REVIEW_REQUIRED
        else:readiness=AssessmentReadiness.READY_FOR_HUMAN_REVIEW
        latest=self._repository.latest(value.subject_reference);version=1 if latest is None else latest.set_version+1
        aid=self._id(value.input_id,str(version),*(x.reference_id for x in state.findings))
        confidence=self._confidence(value,state,joints,evidence,guidelines)
        assessment=OrthopedicAssessment(aid,value.input_id,value.input_version,state.state_reference_id,state.state_version,state.terminology_version,joints,tuple(x.governed_evidence_id for x in evidence),tuple(x.recommendation_id for x in guidelines.recommendations),tuple(sorted(flags)),value.quality.missing_data_references,tuple(sorted({issue for j in joints for p in j.problems for issue in p.limitations})),confidence,readiness,HumanReviewStatus.PENDING_REVIEW,False,self.POLICY,self._clock(),tuple(sorted(set(state.provenance_references)|{x.reference_id for x in value.provenance_references})))
        result=OrthopedicAssessmentSet(self._id(aid,"set"),value.subject_reference,version,latest.set_id if latest else None,assessment,HumanReviewStatus.PENDING_REVIEW,self._clock(),reasoning_input_reference);self._repository.append(result)
        self._event(result,OrthopedicAuditType.GENERATION,actor_id,readiness.value,(aid,))
        for kind,refs in ((OrthopedicAuditType.IMAGING_CORRELATION,tuple(x.imaging_reference_id for j in joints for x in j.imaging)),(OrthopedicAuditType.EVIDENCE_CORRELATION,assessment.governed_evidence_ids),(OrthopedicAuditType.GUIDELINE_CORRELATION,assessment.guideline_recommendation_ids)):
            if refs:self._event(result,kind,actor_id,"CORRELATED",refs)
        if flags:self._event(result,OrthopedicAuditType.CONFLICT,actor_id,"QUALITY_FLAGS",tuple(sorted(flags)))
        return result
    def submit_for_human_review(self,subject_reference,*,reviewer_id,target,justification,generated_by="orthopedic-engine"):
        current=self._repository.latest(subject_reference)
        if current is None:raise OrthopedicBoundaryError("orthopedic assessment does not exist")
        if target is HumanReviewStatus.APPROVED_BY_REVIEWER and current.assessment.readiness is not AssessmentReadiness.READY_FOR_HUMAN_REVIEW:raise OrthopedicBoundaryError("non-ready assessment cannot be approved")
        a=current.assessment;c=a.confidence
        proxy=GovernedClinicalRecommendation(a.assessment_id,a.assessment_id,"Structured orthopedic assessment",1,0,0,a.governed_evidence_ids,(),a.provenance_references,(),(a.policy_version,),GovernedRecommendationExplanation(a.provenance_references,(),(),(),(),(),a.quality_flags,a.limitations,(f"source_completeness={c.source_completeness}",),0,0,0,0,a.review_status),a.review_status,False)
        reviewed=self._review.transition(case_id=subject_reference,recommendation=proxy,target=target,reviewer_id=reviewer_id,justification=justification,generated_by=generated_by)
        version=current.set_version+1;updated=replace(a,review_status=reviewed.review_status,externally_actionable=False);result=replace(current,set_id=self._id(current.set_id,str(version),target.value),set_version=version,previous_set_id=current.set_id,assessment=updated,review_status=target,generated_at=self._clock())
        self._repository.append(result);self._event(result,OrthopedicAuditType.REVIEW_TRANSITION,reviewer_id,target.value,(a.assessment_id,));return result
    def reconstruct(self,subject_reference,version):
        result=next((x for x in self._repository.history(subject_reference) if x.set_version==version),None)
        if result is None:raise OrthopedicBoundaryError("orthopedic assessment version not found")
        return result
    def _guard(self,value):
        if not isinstance(value,ClinicalReasoningInput):raise OrthopedicBoundaryError("only ClinicalReasoningInput is accepted")
        if value.readiness is not ReasoningReadiness.READY_FOR_REASONING or value.quality.review_required or not value.provenance_references:raise OrthopedicBoundaryError("clinical reasoning input is not governed and ready")
    def _concept(self,identifier,version):
        item=self._terminology.get(identifier)
        if not isinstance(item,ClinicalConcept) or item.status is not TerminologyStatus.ACTIVE or item.version!=version:raise OrthopedicBoundaryError("terminology concept is invalid, ambiguous, or version-incompatible")
        return item
    def _evidence_items(self,value):
        result=[]
        for ref in value.evidence.all:
            item=self._evidence.get(ref.reference_id)
            if not isinstance(item,GovernedEvidence) or self._evidence_lifecycle.current_status(item)!="ACTIVE":raise OrthopedicBoundaryError("only active GovernedEvidence references are accepted")
            result.append(item)
        return tuple(result)
    def _guideline_set(self,value):
        result=self._guidelines.latest(value.subject_reference)
        if not isinstance(result,GuidelineRecommendationSet) or result.reasoning_input_id!=value.input_id:raise OrthopedicBoundaryError("governed guideline recommendation set is required")
        allowed={x.reference_id for x in value.applicable_guidelines}
        if any(x.guideline_id not in allowed for x in result.recommendations):raise OrthopedicBoundaryError("guideline recommendation bypass detected")
        return result
    def _joint(self,key,state,evidence,guidelines):
        joint,side=key;findings=tuple(x for x in state.findings if (x.joint,x.laterality)==key);stability=tuple(x for x in state.stability_findings if (x.joint,x.laterality)==key);functional=state.functional
        evid_dirs={d:tuple(sorted(x.governed_evidence_id for x in evidence if d in (x.support_directions or ("INCONCLUSIVE",)))) for d in ("SUPPORTING","OPPOSING","NEUTRAL","INCONCLUSIVE")}
        glines=tuple(self._guideline_correlation(x,{f.concept_id for f in findings}) for x in guidelines.recommendations)
        problems=[];flags=[]
        for finding in findings:
            severity=finding.severity;limitations=[]
            if severity is not Severity.UNKNOWN and not finding.severity_scale_reference:severity=Severity.UNKNOWN;limitations.append("UNSUPPORTED_SEVERITY");flags.append("UNSUPPORTED_SEVERITY")
            status=OrthopedicProblemStatus.SUSPECTED if finding.epistemic_status=="SUSPECTED" else (OrthopedicProblemStatus.CONFIRMED_BY_SOURCE if finding.epistemic_status=="CONFIRMED" else OrthopedicProblemStatus.DOCUMENTED)
            ev=EvidenceCorrelation(finding.reference_id,evid_dirs["SUPPORTING"],evid_dirs["OPPOSING"],evid_dirs["NEUTRAL"],evid_dirs["INCONCLUSIVE"])
            problems.append(OrthopedicProblemAssessment(self._id(finding.reference_id,"problem"),joint,side,status,severity,(finding.reference_id,),(finding.concept_id,),ev,glines,tuple(limitations)))
        imaging=tuple(self._image(x,findings) for x in state.imaging if (x.joint,x.laterality)==key)
        mechanical=MechanicalAssessment(tuple(x.reference_id for x in findings),tuple(x.reference_id for x in findings if x.category in self.MECHANICAL),tuple(x.reference_id for x in findings if x.category is FindingCategory.INSTABILITY),tuple(x.reference_id for x in findings if x.category is FindingCategory.LIMITED_ROM),tuple(x.reference_id for x in functional if x.weight_bearing_tolerance),tuple(x.reference_id for x in functional if x.sports_limitations))
        stable=StabilityAssessment(tuple(x.reference_id for x in stability),tuple(x.test_concept_id for x in stability),side,tuple("UNVERIFIED_EXAMINATION" for x in stability if x.epistemic_status not in {"OBSERVED","CONFIRMED"}))
        align=AlignmentAssessment(tuple(x.reference_id for x in findings if x.category is FindingCategory.ALIGNMENT_ABNORMALITY),side)
        function=FunctionalAssessment(tuple(x.reference_id for x in functional),tuple(x.gait for x in functional if x.gait),tuple(y for x in functional for y in x.adls),tuple(y for x in functional for y in x.work_limitations),tuple(y for x in functional for y in x.sports_limitations),tuple(x.validated_score_reference for x in functional if x.validated_score_reference))
        return JointAssessment(joint,side,tuple(problems),mechanical,stable,align,function,imaging,tuple(x.reference_id for x in state.surgeries if (x.joint,x.laterality)==key),tuple(x.reference_id for x in state.implants if (x.joint,x.laterality)==key),tuple(sorted(set(flags))))
    def _image(self,image,findings):
        exact=tuple(x.reference_id for x in findings if x.concept_id==image.finding_concept_id);same_side=tuple(x.reference_id for x in findings)
        status=ConcordanceStatus.CONCORDANT if exact else (ConcordanceStatus.DISCORDANT if same_side else ConcordanceStatus.INSUFFICIENT_DATA)
        return ImagingCorrelation(image.reference_id,exact,image.finding_concept_id,image.laterality,status,() if exact else ("NO_MATCHING_CLINICAL_FINDING",),(image.provenance,)+tuple(x.provenance for x in findings))
    def _guideline_correlation(self,item,concepts):
        conflicts=tuple(c.conflict_id for c in item.explanation.conflicts)
        if item.readiness is RecommendationReadiness.CONFLICTING_GUIDANCE:status=GuidelineCorrelationStatus.CONFLICTING
        elif item.readiness is RecommendationReadiness.REVIEW_REQUIRED:status=GuidelineCorrelationStatus.REVIEW_REQUIRED
        elif concepts & set(item.applicable_concept_ids):status=GuidelineCorrelationStatus.APPLICABLE
        else:status=GuidelineCorrelationStatus.NOT_APPLICABLE
        return GuidelineCorrelation(item.recommendation_id,status,item.guideline_id,item.guideline_version,item.explanation.strength.name,conflicts)
    def _confidence(self,value,state,joints,evidence,guidelines):
        total=len(state.findings);imaging=[x for j in joints for x in j.imaging]
        return OrthopedicConfidence(1-min(len(value.quality.missing_data_references)/max(total,1),1),value.quality.terminology_confidence,min(len(state.stability_findings)/max(total,1),1),sum(x.status is ConcordanceStatus.CONCORDANT for x in imaging)/max(len(imaging),1),min(len(evidence)/max(total,1),1),min(len(guidelines.recommendations)/max(total,1),1),min(len(value.quality.conflicting_data_references)/max(total,1),1),self.CONFIDENCE_POLICY)
    def _event(self,value,kind,actor,decision,refs):self._audit.append(OrthopedicAuditEvent(self._id(value.set_id,kind.value,decision,*refs),value.subject_reference,value.set_id,kind,self._clock(),actor,decision,tuple(refs),self.POLICY))
    def _blocked(self,value,actor,decision):self._audit.append(OrthopedicAuditEvent(self._id(value.input_id,"blocked",decision),value.subject_reference,value.input_id,OrthopedicAuditType.BLOCKED,self._clock(),actor,decision,(value.input_id,),self.POLICY))
    @staticmethod
    def _id(*parts):return "ortho_"+sha256("|".join(parts).encode()).hexdigest()
