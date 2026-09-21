from __future__ import annotations
from dataclasses import replace
from hashlib import sha256
from .domain import *
from jmoraIs.reasoning_input.domain import ClinicalReasoningInput,ReasoningReadiness
from jmoraIs.appraisal.governed import GovernedEvidence
from jmoraIs.terminology.domain import ClinicalConcept,TerminologyStatus
from jmoraIs.clinical.governed import GovernedClinicalRecommendation,GovernedRecommendationExplanation

def guideline_validity_issue(guideline,input,*,as_of):
    if guideline.withdrawn_at and as_of>=guideline.withdrawn_at:return "GUIDELINE_WITHDRAWN"
    if guideline.superseded_by:return "GUIDELINE_SUPERSEDED"
    if guideline.expiration_date and as_of>guideline.expiration_date:return "GUIDELINE_EXPIRED"
    if not guideline.appraisal_approved:return "APPRAISAL_INCOMPLETE"
    if guideline.terminology_version!=input.terminology_version:return "TERMINOLOGY_VERSION_MISMATCH"
    if guideline.policy_version not in {item.policy_version for item in input.policy_versions}:return "POLICY_VERSION_MISMATCH"
    return None

class GuidelineRecommendationEngine:
    RANKING_POLICY="MIP-06-RANK-1";CONFIDENCE_POLICY="MIP-06-CONFIDENCE-1"
    QUALITY={"HIGH":1.0,"MODERATE":.75,"LOW":.4,"VERY_LOW":.15};CERTAINTY={"HIGH":1.0,"MODERATE":.75,"LOW":.4,"VERY_LOW":.15}
    def __init__(self,guidelines,evidence,lifecycle,terminology,repository,audit,review_service,*,clock):
        self._guidelines=guidelines;self._evidence=evidence;self._lifecycle=lifecycle;self._terminology=terminology;self._repository=repository;self._audit=audit;self._review=review_service;self._clock=clock
    def create_recommendation_set(self,reasoning_input,concept_ids=(),contraindication_ids=(),*,actor_id="engine"):
        self._guard_input(reasoning_input);concepts=self._resolve_concepts(concept_ids);contra=self._resolve_concepts(contraindication_ids)
        guideline_ids=tuple(item.reference_id for item in reasoning_input.applicable_guidelines);guidelines=self._guidelines.applicable(guideline_ids)
        candidates=[];excluded=[]
        for guideline in guidelines:
            issue=self._validity_issue(guideline,reasoning_input)
            if issue:excluded.append((guideline,issue));continue
            applicability=self.evaluate_applicability(reasoning_input,guideline,concepts,contra)
            self._audit_event(reasoning_input.subject_reference,"pending",RecommendationAuditType.APPLICABILITY,actor_id,applicability.outcome.value,(guideline.guideline_id,),guideline.policy_version)
            if applicability.outcome is ApplicabilityOutcome.NOT_APPLICABLE:continue
            evidence=self._resolve_evidence(guideline,reasoning_input,excluded)
            if not evidence:continue
            candidates.append(self._candidate(reasoning_input,guideline,applicability,evidence,concepts))
        conflicts=self.detect_conflicts(tuple(candidates));ranked=self.rank_recommendations(tuple(candidates),conflicts)
        latest=self._repository.latest(reasoning_input.subject_reference);version=1 if latest is None else latest.set_version+1
        if not ranked:readiness=RecommendationReadiness.NO_APPLICABLE_GUIDELINE
        elif any(item.severity is ConflictSeverity.CRITICAL_CONFLICT and not item.resolved for item in conflicts):readiness=RecommendationReadiness.CONFLICTING_GUIDANCE
        elif any(item.readiness is RecommendationReadiness.REVIEW_REQUIRED for item in ranked):readiness=RecommendationReadiness.REVIEW_REQUIRED
        else:readiness=RecommendationReadiness.READY_FOR_HUMAN_REVIEW
        set_id=self._id(reasoning_input.input_id,str(version),*(item.recommendation_id for item in ranked))
        value=GuidelineRecommendationSet(set_id,reasoning_input.subject_reference,version,latest.set_id if latest else None,reasoning_input.input_id,ranked,readiness,HumanReviewStatus.PENDING_REVIEW,
          self.RANKING_POLICY,self._clock(),tuple(sorted({ref for item in ranked for ref in item.provenance_references})) or tuple(ref.reference_id for ref in reasoning_input.provenance_references))
        self._repository.append(value)
        for guideline,issue in excluded:self._audit_event(value.subject_reference,value.set_id,RecommendationAuditType.EVIDENCE_EXCLUDED,actor_id,issue,(guideline.guideline_id,),guideline.policy_version)
        self._audit_event(value.subject_reference,value.set_id,RecommendationAuditType.GENERATION,actor_id,readiness.value,tuple(item.recommendation_id for item in ranked),value.policy_version)
        if conflicts:self._audit_event(value.subject_reference,value.set_id,RecommendationAuditType.CONFLICT,actor_id,max(item.severity.value for item in conflicts),tuple(item.conflict_id for item in conflicts),value.policy_version)
        return value
    def evaluate_applicability(self,input,guideline,concepts,contra):
        input_ref=next((item for item in input.applicable_guidelines if item.reference_id==guideline.guideline_id and item.guideline_version==guideline.guideline_version),None)
        if input_ref is None:return RecommendationApplicability(ApplicabilityOutcome.NOT_APPLICABLE,(),(),("GUIDELINE_REFERENCE",),ContraindicationStatus.UNKNOWN)
        contexts=set(input_ref.applicability);required=set(guideline.applicability.population_contexts);matched=tuple(sorted(contexts&required));missing=[]
        if required and not required.issubset(contexts):missing.append("POPULATION_CONTEXT")
        concept_set={item.canonical_id for item in concepts};required_concepts=set(guideline.applicability.required_concept_ids);matched_concepts=tuple(sorted(concept_set&required_concepts))
        if required_concepts and not required_concepts.issubset(concept_set):missing.append("CLINICAL_CONCEPT")
        contra_set={item.canonical_id for item in contra};required_contra=set(guideline.applicability.contraindication_concept_ids)
        contra_status=ContraindicationStatus.PRESENT if contra_set&required_contra else (ContraindicationStatus.ABSENT if required_contra and contra_set else ContraindicationStatus.UNKNOWN)
        outcome=ApplicabilityOutcome.REVIEW_REQUIRED if missing or any(value is not None for value in (guideline.applicability.age_min,guideline.applicability.age_max,guideline.applicability.sex,guideline.applicability.stage)) else ApplicabilityOutcome.APPLICABLE
        return RecommendationApplicability(outcome,matched,matched_concepts,tuple(missing),contra_status)
    def detect_conflicts(self,candidates):
        conflicts=[]
        for index,left in enumerate(candidates):
            for right in candidates[index+1:]:
                dimensions=[]
                if left.intent!=right.intent:dimensions.append("DIRECTION")
                if left.explanation.strength!=right.explanation.strength:dimensions.append("STRENGTH")
                if left.explanation.organization!=right.explanation.organization:dimensions.append("ORGANIZATION")
                if left.guideline_version!=right.guideline_version:dimensions.append("VERSION")
                if not dimensions:continue
                positive={RecommendationIntent.RECOMMEND,RecommendationIntent.CONSIDER};negative={RecommendationIntent.AVOID,RecommendationIntent.DO_NOT_RECOMMEND}
                critical=bool({left.intent,right.intent}&positive and {left.intent,right.intent}&negative)
                severity=ConflictSeverity.CRITICAL_CONFLICT if critical else (ConflictSeverity.MATERIAL_CONFLICT if "DIRECTION" in dimensions else ConflictSeverity.MINOR_CONFLICT)
                conflicts.append(RecommendationConflict(self._id(left.recommendation_id,right.recommendation_id),severity,(left.guideline_id,right.guideline_id),tuple(dimensions)))
        return tuple(conflicts)
    def rank_recommendations(self,candidates,conflicts):
        burden={item.guideline_id:0 for item in candidates}
        for conflict in conflicts:
            amount={ConflictSeverity.MINOR_CONFLICT:.2,ConflictSeverity.MATERIAL_CONFLICT:.6,ConflictSeverity.CRITICAL_CONFLICT:1}.get(conflict.severity,0)
            for gid in conflict.guideline_ids:burden[gid]=max(burden.get(gid,0),amount)
        scored=[]
        for item in candidates:
            c=item.confidence;score=round(.25*c.guideline_quality+.25*c.evidence_quality+.25*c.applicability+.15*item.ranking_score+.10*(1-burden.get(item.guideline_id,0)),4)
            readiness=RecommendationReadiness.CONFLICTING_GUIDANCE if burden.get(item.guideline_id)==1 else item.readiness
            relevant=tuple(conflict for conflict in conflicts if item.guideline_id in conflict.guideline_ids)
            scored.append(replace(item,ranking_score=score,readiness=readiness,confidence=replace(c,conflict_burden=burden.get(item.guideline_id,0),aggregate=round((c.input_completeness+c.evidence_quality+c.guideline_quality+c.applicability+c.terminology_confidence+(1-burden.get(item.guideline_id,0)))/6,4)),explanation=replace(item.explanation,conflicts=relevant)))
        ordered=sorted(scored,key=lambda item:(-item.ranking_score,item.guideline_id,item.recommendation_id));return tuple(replace(item,rank=index+1) for index,item in enumerate(ordered))
    def submit_for_human_review(self,subject_reference,*,reviewer_id,target,justification,generated_by="engine"):
        current=self._repository.latest(subject_reference)
        if current is None or not current.recommendations:raise GuidelineBoundaryRejected("recommendation set does not exist")
        if target is HumanReviewStatus.APPROVED_BY_REVIEWER and any(item.readiness is RecommendationReadiness.CONFLICTING_GUIDANCE for item in current.recommendations):raise GuidelineBoundaryRejected("critical conflict requires adjudication before approval")
        updated=[]
        for item in current.recommendations:
            proxy=GovernedClinicalRecommendation(item.recommendation_id,item.guideline_recommendation_id,item.statement,item.rank,item.ranking_score,item.confidence.aggregate,item.governed_evidence_ids,(),item.provenance_references,(),(item.policy_version,),
              GovernedRecommendationExplanation(item.explanation.basis.supporting,item.explanation.appraisal_quality and (item.explanation.appraisal_quality,) or (),(),(item.explanation.organization,),(item.explanation.strength.name,),item.explanation.applicability.matched_contexts,tuple(dim for conflict in item.explanation.conflicts for dim in conflict.dimensions),item.explanation.limitations,(),0,0,0,0,item.review_status),item.review_status,False)
            reviewed=self._review.transition(case_id=subject_reference,recommendation=proxy,target=target,reviewer_id=reviewer_id,justification=justification,generated_by=generated_by)
            updated.append(replace(item,review_status=reviewed.review_status,externally_actionable=reviewed.externally_actionable,explanation=replace(item.explanation,human_review_status=reviewed.review_status)))
        version=current.set_version+1;value=replace(current,set_id=self._id(current.set_id,str(version),target.value),set_version=version,previous_set_id=current.set_id,recommendations=tuple(updated),review_status=target,generated_at=self._clock())
        self._repository.append(value);self._audit_event(subject_reference,value.set_id,RecommendationAuditType.HUMAN_REVIEW,reviewer_id,target.value,tuple(item.recommendation_id for item in updated),value.policy_version);return value
    def reconstruct(self,subject_reference,version):
        value=next((item for item in self._repository.history(subject_reference) if item.set_version==version),None)
        if value is None:raise GuidelineBoundaryRejected("recommendation version not found")
        return value
    def _guard_input(self,value):
        if not isinstance(value,ClinicalReasoningInput):raise GuidelineBoundaryRejected("only ClinicalReasoningInput is accepted")
        if value.readiness is not ReasoningReadiness.READY_FOR_REASONING:raise GuidelineBoundaryRejected("reasoning input is not ready")
        if value.quality.review_required or not value.provenance_references:raise GuidelineBoundaryRejected("reasoning input requires review or provenance")
    def _resolve_concepts(self,identifiers):
        result=[]
        for identifier in identifiers:
            item=self._terminology.get(identifier)
            if not isinstance(item,ClinicalConcept) or item.status is not TerminologyStatus.ACTIVE:raise GuidelineBoundaryRejected("terminology concept is invalid or ambiguous")
            result.append(item)
        return tuple(result)
    def _validity_issue(self,guideline,input):
        return guideline_validity_issue(guideline,input,as_of=self._clock().date())
    def _resolve_evidence(self,guideline,input,excluded):
        allowed={item.reference_id for item in input.evidence.all};items=[]
        for identifier in guideline.governed_evidence_ids:
            if identifier not in allowed:continue
            item=self._evidence.get(identifier)
            if not isinstance(item,GovernedEvidence) or self._lifecycle.current_status(item)!="ACTIVE":continue
            items.append(item)
        return tuple(items)
    def _candidate(self,input,guideline,app,evidence,concepts):
        directions={key:[] for key in ("SUPPORTING","OPPOSING","NEUTRAL","INCONCLUSIVE")}
        for item in evidence:
            for direction in item.support_directions or ("INCONCLUSIVE",):directions[direction if direction in directions else "INCONCLUSIVE"].append(item.governed_evidence_id)
        basis=RecommendationBasis(tuple(item.governed_evidence_id for item in evidence),*(tuple(directions[key]) for key in ("SUPPORTING","OPPOSING","NEUTRAL","INCONCLUSIVE")))
        eq=sum(self.QUALITY.get(item.methodological_quality,0) for item in evidence)/len(evidence);gq=self.QUALITY.get(guideline.methodological_quality,0);ap=1 if app.outcome is ApplicabilityOutcome.APPLICABLE else .5
        confidence=RecommendationConfidence(input.quality.overall_input_completeness,eq,gq,ap,input.quality.terminology_confidence,0,0,self.CONFIDENCE_POLICY)
        readiness=RecommendationReadiness.REVIEW_REQUIRED if app.outcome is ApplicabilityOutcome.REVIEW_REQUIRED else RecommendationReadiness.READY_FOR_HUMAN_REVIEW
        explanation=RecommendationExplanation(guideline.guideline_id,guideline.guideline_version,guideline.organization,guideline.strength,guideline.evidence_certainty,guideline.methodological_quality,app,tuple(item.canonical_id for item in concepts),basis,(),app.contraindication_status,(),input.quality.conflicting_data_references,HumanReviewStatus.PENDING_REVIEW)
        rec_id=self._id(input.input_id,guideline.guideline_recommendation_id)
        recency=max(0,1-min((self._clock().date()-guideline.publication_date).days/3650,1))
        return GuidelineRecommendation(rec_id,guideline.guideline_recommendation_id,guideline.statement,guideline.intent,0,recency,input.input_id,input.input_version,tuple(item.governed_evidence_id for item in evidence),guideline.guideline_id,guideline.guideline_version,(guideline.terminology_version,),tuple(item.canonical_id for item in concepts),guideline.appraisal_version,guideline.policy_version,readiness,HumanReviewStatus.PENDING_REVIEW,False,confidence,explanation,tuple(guideline.provenance_references)+tuple(ref for item in evidence for ref in item.provenance_references),self._clock())
    def _audit_event(self,subject,set_id,kind,actor,decision,refs,policy):self._audit.append(RecommendationAuditEvent(self._id(subject,set_id,kind.value,decision,*refs),subject,set_id,kind,self._clock(),actor,decision,tuple(refs),policy))
    @staticmethod
    def _id(*parts):return "gr_"+sha256("|".join(parts).encode()).hexdigest()
