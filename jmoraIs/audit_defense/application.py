from __future__ import annotations
from dataclasses import replace
from hashlib import sha256
from jmoraIs.appraisal.governed import GovernedEvidence
from jmoraIs.clinical.governed import GovernedClinicalRecommendation,GovernedRecommendationExplanation,HumanReviewStatus
from jmoraIs.guideline_engine.domain import GuidelineRecommendationSet
from jmoraIs.orthopedic_intelligence.domain import OrthopedicAssessmentSet
from jmoraIs.reasoning_input.domain import ClinicalReasoningInput,ReasoningReadiness
from jmoraIs.terminology.domain import ClinicalConcept,TerminologyStatus
from .domain import *
class AuditDefenseService:
    POLICY="MIP-09.1"
    def __init__(self,clinical,evidence,lifecycle,guidelines,orthopedic,terminology,repository,audit,review_service,*,clock):self._clinical=clinical;self._evidence=evidence;self._lifecycle=lifecycle;self._guidelines=guidelines;self._orthopedic=orthopedic;self._terminology=terminology;self._repository=repository;self._audit=audit;self._review=review_service;self._clock=clock
    def generate(self,value,*,actor_id="audit-defense-engine"):
        self._guard(value);clinical=self._clinical_support(value);scientific=self._scientific_support(value);guidelines=self._guideline_support(value);orthopedic=self._orthopedic_set(value);self._validate_terminology(clinical,value.terminology_version)
        limitations=self._limitations(value,clinical,scientific,guidelines,orthopedic);counter=self._counterarguments(scientific,guidelines,limitations);position=self._position(scientific,guidelines,limitations)
        facts=clinical or (ClinicalSupport("NOT_DOCUMENTED",value.patient_clinical_state.reference_id,value.patient_clinical_state.clinical_state_version,"UNKNOWN",(),orthopedic.assessment.assessment_id,tuple(x.reference_id for x in value.provenance_references)),)
        arguments=tuple(self._argument(fact,position,scientific,guidelines,counter,limitations,value) for fact in facts)
        conflicts=tuple(sorted({ref for x in guidelines for ref in x.conflict_references}));explain=DefenseExplainability(self._by_direction(scientific,SupportDirection.SUPPORTING),self._by_direction(scientific,SupportDirection.OPPOSING),self._by_direction(scientific,SupportDirection.NEUTRAL),self._by_direction(scientific,SupportDirection.INCONCLUSIVE),tuple(x.recommendation_id for x in guidelines),tuple(x.fact_id for x in facts),conflicts,tuple(x.limitation_id for x in limitations),(value.terminology_version,),tuple(sorted({x.policy_version for x in value.policy_versions}|{self.POLICY})))
        status=DefenseStatus.REVIEW_REQUIRED if position in {ArgumentPosition.CONFLICTED,ArgumentPosition.INSUFFICIENT,ArgumentPosition.REVIEW_REQUIRED} else DefenseStatus.DRAFT
        stream=self._id(value.subject_reference,"audit-defense");latest=self._repository.latest(stream);version=1 if latest is None else latest.version+1
        if latest:self._event(latest,AuditDefenseEventType.SUPERSESSION,actor_id,"SUPERSEDED",(latest.package_id,))
        defense_id=self._id(stream,str(version),*(x.argument_id for x in arguments));provenance=tuple(sorted({x.reference_id for x in value.provenance_references}|{r for x in arguments for r in x.provenance_references}))
        defense=AuditDefense(defense_id,value.subject_reference,value.input_id,value.input_version,value.patient_clinical_state.reference_id,value.patient_clinical_state.clinical_state_version,orthopedic.set_id,orthopedic.set_version,arguments,explain,status,HumanReviewStatus.PENDING_REVIEW,False,self._clock(),provenance)
        package=DefensePackage(self._id(defense_id,"package"),stream,version,latest.package_id if latest else None,defense,None,None,self._clock());self._repository.append(package)
        self._event(package,AuditDefenseEventType.GENERATION,actor_id,status.value,(defense_id,));self._event(package,AuditDefenseEventType.EVIDENCE_AGGREGATION,actor_id,"AGGREGATED",tuple(x.governed_evidence_id for x in scientific));self._event(package,AuditDefenseEventType.GUIDELINE_AGGREGATION,actor_id,"AGGREGATED",tuple(x.recommendation_id for x in guidelines))
        if conflicts:self._event(package,AuditDefenseEventType.CONFLICT_EXPOSITION,actor_id,"EXPOSED",conflicts)
        if limitations:self._event(package,AuditDefenseEventType.LIMITATION_EXPOSITION,actor_id,"EXPOSED",tuple(x.limitation_id for x in limitations))
        if counter:self._event(package,AuditDefenseEventType.COUNTERARGUMENT_GENERATION,actor_id,"SOURCE_BOUND",tuple(x.counterargument_id for x in counter))
        return package
    def submit_for_review(self,stream_id,*,reviewer_id,target,justification,generated_by="audit-defense-engine"):
        current=self._repository.latest(stream_id)
        if current is None:raise AuditDefenseBoundaryRejected("defense does not exist")
        if target is HumanReviewStatus.APPROVED_BY_REVIEWER and current.defense.status is DefenseStatus.REVIEW_REQUIRED:raise AuditDefenseBoundaryRejected("conflicted or insufficient defense cannot be approved")
        d=current.defense;e=d.explainability
        proxy=GovernedClinicalRecommendation(d.defense_id,d.defense_id,"Structured audit defense",1,0,0,e.supporting_evidence_ids+e.opposing_evidence_ids+e.neutral_evidence_ids+e.inconclusive_evidence_ids,(),d.provenance_references,(),e.policy_versions,GovernedRecommendationExplanation(d.provenance_references,(),(),(),(),(),e.conflict_references,e.limitation_ids,(),0,0,0,0,d.review_status),d.review_status,False)
        reviewed=self._review.transition(case_id=stream_id,recommendation=proxy,target=target,reviewer_id=reviewer_id,justification=justification,generated_by=generated_by)
        status=DefenseStatus.APPROVED_BY_REVIEWER if target is HumanReviewStatus.APPROVED_BY_REVIEWER else (DefenseStatus.REJECTED_BY_REVIEWER if target is HumanReviewStatus.REJECTED_BY_REVIEWER else DefenseStatus.UNDER_REVIEW)
        version=current.version+1;defense=replace(d,defense_id=self._id(d.defense_id,str(version),target.value),status=status,review_status=reviewed.review_status,externally_actionable=False,generated_at=self._clock());result=DefensePackage(self._id(defense.defense_id,"package"),stream_id,version,current.package_id,defense,reviewer_id,justification,self._clock(),current.stage11_document_reference);self._repository.append(result);self._event(result,AuditDefenseEventType.REVIEW_TRANSITION,reviewer_id,target.value,(current.package_id,));return result
    def reconstruct(self,stream_id,version):
        result=next((x for x in self._repository.history(stream_id) if x.version==version),None)
        if result is None:raise AuditDefenseBoundaryRejected("defense version not found")
        return result
    def _guard(self,value):
        if not isinstance(value,ClinicalReasoningInput):raise AuditDefenseBoundaryRejected("only ClinicalReasoningInput is accepted")
        if value.readiness is not ReasoningReadiness.READY_FOR_REASONING or value.quality.review_required or not value.provenance_references:raise AuditDefenseBoundaryRejected("reasoning input is not governed and ready")
    def _clinical_support(self,value):
        facts=self._clinical.facts(value.patient_clinical_state.reference_id)
        if not isinstance(facts,tuple) or any(not isinstance(x,GovernedAuditClinicalFact) or x.clinical_state_version!=value.patient_clinical_state.clinical_state_version or not x.provenance_references for x in facts):raise AuditDefenseBoundaryRejected("governed clinical state references are required")
        return tuple(ClinicalSupport(x.fact_id,x.clinical_state_reference_id,x.clinical_state_version,x.epistemic_status,x.terminology_concept_ids,None,x.provenance_references) for x in facts)
    def _scientific_support(self,value):
        result=[]
        for ref in value.evidence.all:
            item=self._evidence.get(ref.reference_id)
            if not isinstance(item,GovernedEvidence) or self._lifecycle.current_status(item)!="ACTIVE" or not item.provenance_references or not item.ledger_references:raise AuditDefenseBoundaryRejected("only active GovernedEvidence is accepted")
            directions=item.support_directions or ("INCONCLUSIVE",)
            result.extend(ScientificSupport(item.governed_evidence_id,item.evidence_package_id,SupportDirection(x if x in SupportDirection._value2member_map_ else "INCONCLUSIVE"),item.evidence_level,item.methodological_quality,item.provenance_references,item.ledger_references) for x in directions)
        return tuple(result)
    def _guideline_support(self,value):
        source=self._guidelines.latest(value.subject_reference)
        if not isinstance(source,GuidelineRecommendationSet) or source.reasoning_input_id!=value.input_id:raise AuditDefenseBoundaryRejected("governed guideline set is required")
        allowed={x.reference_id for x in value.applicable_guidelines};result=[]
        for x in source.recommendations:
            if x.guideline_id not in allowed:raise AuditDefenseBoundaryRejected("guideline bypass detected")
            result.append(GuidelineSupport(x.recommendation_id,x.guideline_id,x.guideline_version,x.explanation.organization,x.explanation.strength.name,x.review_status,tuple(c.conflict_id for c in x.explanation.conflicts),x.explanation.limitations,x.provenance_references))
        return tuple(result)
    def _orthopedic_set(self,value):
        result=self._orthopedic.latest(value.subject_reference)
        if not isinstance(result,OrthopedicAssessmentSet) or result.assessment.reasoning_input_id!=value.input_id:raise AuditDefenseBoundaryRejected("governed OrthopedicAssessmentSet is required")
        return result
    def _validate_terminology(self,clinical,version):
        for identifier in {x for fact in clinical for x in fact.terminology_concept_ids}:
            item=self._terminology.get(identifier)
            if not isinstance(item,ClinicalConcept) or item.status is not TerminologyStatus.ACTIVE or item.version!=version:raise AuditDefenseBoundaryRejected("active governed terminology is required")
    def _limitations(self,value,clinical,scientific,guidelines,orthopedic):
        values=[]
        for code,refs,severity in (("MISSING_CLINICAL_DATA",value.quality.missing_data_references,LimitationSeverity.MATERIAL),("CONFLICTING_CLINICAL_DATA",value.quality.conflicting_data_references,LimitationSeverity.CRITICAL),("STALE_CLINICAL_DATA",value.quality.stale_data_references,LimitationSeverity.MATERIAL)):
            if refs:values.append(Limitation(self._id(code,*refs),code,severity,tuple(refs),self.POLICY))
        for ref in sorted({r for x in guidelines for r in x.conflict_references}):values.append(Limitation(self._id("GUIDELINE_CONFLICT",ref),"GUIDELINE_CONFLICT",LimitationSeverity.CRITICAL,(ref,),self.POLICY))
        for code in orthopedic.assessment.limitations:values.append(Limitation(self._id("ORTHOPEDIC_LIMITATION",code),"ORTHOPEDIC_LIMITATION",LimitationSeverity.MATERIAL,(code,),self.POLICY))
        if not clinical:values.append(Limitation(self._id("NO_GOVERNED_CLINICAL_FACT"),"NO_GOVERNED_CLINICAL_FACT",LimitationSeverity.CRITICAL,(),self.POLICY))
        if not scientific:values.append(Limitation(self._id("NO_GOVERNED_EVIDENCE"),"NO_GOVERNED_EVIDENCE",LimitationSeverity.CRITICAL,(),self.POLICY))
        if not guidelines:values.append(Limitation(self._id("NO_APPLICABLE_GUIDELINE"),"NO_APPLICABLE_GUIDELINE",LimitationSeverity.MATERIAL,(),self.POLICY))
        return tuple(values)
    def _counterarguments(self,scientific,guidelines,limitations):
        result=[];opposing=tuple(x.governed_evidence_id for x in scientific if x.direction is SupportDirection.OPPOSING)
        if opposing:result.append(CounterArgument(self._id("OPPOSING_EVIDENCE",*opposing),"OPPOSING_EVIDENCE_PRESENT",opposing,(SupportDirection.OPPOSING,),()))
        conflicts=tuple(sorted({r for x in guidelines for r in x.conflict_references}))
        if conflicts:result.append(CounterArgument(self._id("GUIDELINE_CONFLICT",*conflicts),"GUIDELINE_CONFLICT_PRESENT",conflicts,(),tuple(x.limitation_id for x in limitations if x.code=="GUIDELINE_CONFLICT")))
        return tuple(result)
    def _position(self,scientific,guidelines,limitations):
        if any(x.severity is LimitationSeverity.CRITICAL for x in limitations):return ArgumentPosition.CONFLICTED
        directions={x.direction for x in scientific}
        if SupportDirection.SUPPORTING in directions and SupportDirection.OPPOSING in directions:return ArgumentPosition.CONFLICTED
        if SupportDirection.SUPPORTING in directions:return ArgumentPosition.SUPPORTED
        if SupportDirection.OPPOSING in directions:return ArgumentPosition.OPPOSED
        return ArgumentPosition.INSUFFICIENT
    def _argument(self,fact,position,scientific,guidelines,counter,limitations,value):
        provenance=tuple(sorted(set(fact.provenance_references)|{r for x in scientific for r in x.provenance_references}|{r for x in guidelines for r in x.provenance_references}))
        return DefenseArgument(self._id(fact.fact_id,"argument"),"SOURCE_BOUND_TECHNICAL_ARGUMENT",position,(fact,),scientific,guidelines,counter,limitations,fact.terminology_concept_ids,tuple(sorted({x.policy_version for x in value.policy_versions}|{self.POLICY})),provenance)
    @staticmethod
    def _by_direction(items,direction):return tuple(sorted({x.governed_evidence_id for x in items if x.direction is direction}))
    def _event(self,value,kind,actor,decision,refs):self._audit.append(AuditDefenseEvent(self._id(value.package_id,kind.value,decision,*refs),value.stream_id,value.package_id,kind,self._clock(),actor,decision,tuple(refs),self.POLICY))
    @staticmethod
    def _id(*parts):return "def_"+sha256("|".join(parts).encode()).hexdigest()

class AuditDefenseTraceabilityService:
    """Appends workflow lineage without making document prose a reasoning input."""
    POLICY="STAGE11-STAGE12-TRACE-1"
    def __init__(self,documents,repository,audit,*,clock):self._documents,self._repository,self._audit,self._clock=documents,repository,audit,clock
    def link_stage11_document(self,defense_reference,document_reference,*,actor_id="traceability-service"):
        if not isinstance(defense_reference,PersistedDefensePackageReference) or defense_reference.state is not DefenseReferenceState.PRE_LINK:
            raise AuditDefenseBoundaryRejected("owner-issued PRE_LINK reference is required")
        current=self._repository.get_exact(defense_reference)
        if not isinstance(current,DefensePackage):raise AuditDefenseBoundaryRejected("persisted DefensePackage is required")
        if current.stage11_document_reference is not None:raise AuditDefenseBoundaryRejected("Stage-11 document reference is immutable")
        if not isinstance(document_reference,PersistedMedicalDocumentVersionReference):raise AuditDefenseBoundaryRejected("owner-issued MedicalDocumentVersion reference is required")
        from jmoraIs.tenancy.context import current_tenant_context
        if document_reference.tenant_id!=current_tenant_context().tenant_id or document_reference.tenant_id!=defense_reference.tenant_id:
            raise AuditDefenseBoundaryRejected("Stage-11 tenant mismatch")
        self._documents.get_exact(document_reference)
        reference=document_reference
        version=current.version+1
        package_id=self._id(current.package_id,"stage11",reference.document_stream_id,str(reference.version),reference.integrity_hash)
        result=DefensePackage(package_id,current.stream_id,version,current.package_id,current.defense,None,None,self._clock(),reference)
        linked_reference=self._repository.append_linked_reference(defense_reference,result)
        self._audit.append(AuditDefenseEvent(self._id(package_id,"trace-linked"),result.stream_id,package_id,AuditDefenseEventType.TRACE_LINKED,self._clock(),actor_id,"EXACT_STAGE11_REFERENCE",(current.package_id,reference.document_stream_id,reference.document_id,str(reference.version),reference.integrity_hash),self.POLICY))
        return linked_reference
    def resolve_stage11_document(self,reference):
        if not isinstance(reference,PersistedDefensePackageReference) or reference.state is not DefenseReferenceState.STAGE11_LINKED:
            raise AuditDefenseBoundaryRejected("owner-issued STAGE11_LINKED reference is required")
        package=self._repository.get_exact(reference)
        if not isinstance(package.stage11_document_reference,PersistedMedicalDocumentVersionReference):raise AuditDefenseBoundaryRejected("owner-issued Stage-11 reference is required")
        return self._documents.get_exact(package.stage11_document_reference)
    @staticmethod
    def _id(*parts):return "def_"+sha256("|".join(parts).encode()).hexdigest()
