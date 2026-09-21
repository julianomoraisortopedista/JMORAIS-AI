from __future__ import annotations
from dataclasses import dataclass,replace
from hashlib import sha256
from .domain import *
from jmoraIs.terminology.domain import MappingReviewStatus,MappingType

@dataclass(frozen=True)
class ClinicalReasoningInputDraft:
    subject_reference:str;patient_clinical_state:PatientClinicalStateReference;terminology_version:str
    evidence:EvidenceReferenceSummary;evidence_packages:tuple[EvidencePackageReference,...]
    applicable_guidelines:tuple[GuidelineReference,...];timeline:TimelineReference;quality:DataQualitySummary
    provenance_references:tuple[TraceableReference,...];audit_references:tuple[AuditReference,...]
    policy_versions:tuple[PolicyVersionReference,...];review_status:ReasoningReviewStatus=ReasoningReviewStatus.AUTO_ASSEMBLED
    terminology_governance_references:tuple=()
    clinical_state_reference:object|None=None
    governed_evidence_references:tuple=()

class ClinicalReasoningInputService:
    """Builds and governs a reference contract; performs no clinical reasoning."""
    def __init__(self,repository,audit,*,clock,terminology_governance=None,clinical_states=None,governed_evidence=None):self._repository=repository;self._audit=audit;self._clock=clock;self._terminology_governance=terminology_governance;self._clinical_states=clinical_states;self._governed_evidence=governed_evidence
    def build(self,draft,*,actor_id,source_reference):
        if not isinstance(draft,ClinicalReasoningInputDraft):raise InvalidReasoningInput("typed reasoning-input draft is required")
        references=self._validate_terminology(draft.terminology_version,draft.terminology_governance_references)
        state_reference,evidence_references=self._validate_exact_upstream(draft,references)
        latest=self._repository.latest(draft.subject_reference);version=1 if latest is None else latest.input_version+1
        readiness=self.calculate_readiness(draft.review_status,draft.quality,draft.evidence,draft.applicable_guidelines)
        value=ClinicalReasoningInput(self._id(draft.subject_reference,str(version),draft.patient_clinical_state.reference_id),draft.subject_reference,
          version,latest.input_id if latest else None,self._clock(),draft.patient_clinical_state,draft.terminology_version,draft.evidence,
          draft.evidence_packages,draft.applicable_guidelines,draft.timeline,draft.review_status,readiness,draft.quality,
          draft.provenance_references,draft.audit_references,draft.policy_versions,references,state_reference,evidence_references)
        self._repository.append(value);self._event(value,ReasoningAuditType.CREATION,actor_id,source_reference,"CREATED");return value
    def _validate_terminology(self,terminology_version,references):
        references=tuple(sorted(references,key=lambda item:item.reference_id))
        if not references:return ()
        if self._terminology_governance is None:raise InvalidReasoningInput("canonical terminology governance query port is required")
        if len({item.reference_id for item in references})!=len(references):raise InvalidReasoningInput("duplicate terminology governance reference")
        for reference in references:
            try:record=self._terminology_governance.get_exact(reference)
            except Exception as exc:raise InvalidReasoningInput("terminology governance reference is invalid") from exc
            if record.terminology_version!=terminology_version or record.review_required or record.review_status in {MappingReviewStatus.REVIEW_REQUIRED,MappingReviewStatus.REJECTED} or record.mapping_type is MappingType.UNMAPPED:raise InvalidReasoningInput("terminology governance is not eligible for reasoning input")
        return references
    def _validate_exact_upstream(self,draft,terminology_references):
        state_reference=draft.clinical_state_reference
        evidence_references=tuple(sorted(draft.governed_evidence_references,key=lambda item:item.reference_id))
        requested=(state_reference is not None,bool(evidence_references),bool(terminology_references))
        if not any(requested[:2]):return None,()
        if not all(requested):raise InvalidReasoningInput("complete exact upstream lineage is required")
        if self._clinical_states is None or self._governed_evidence is None:raise InvalidReasoningInput("canonical exact upstream query ports are required")
        if len({item.reference_id for item in evidence_references})!=len(evidence_references):raise InvalidReasoningInput("duplicate exact GovernedEvidence reference")
        try:state=self._clinical_states.get_exact(state_reference)
        except Exception as exc:raise InvalidReasoningInput("exact Clinical State reference is invalid") from exc
        legacy=draft.patient_clinical_state
        if (state.state_id,state.state_version,state.patient_context_version)!=(legacy.reference_id,legacy.clinical_state_version,legacy.patient_context_version):raise InvalidReasoningInput("Clinical State exact reference mismatch")
        expected={item.reference_id:item for item in draft.evidence.all}
        resolved=[]
        for reference in evidence_references:
            try:evidence=self._governed_evidence.get_exact(reference)
            except Exception as exc:raise InvalidReasoningInput("exact GovernedEvidence reference is invalid") from exc
            legacy_evidence=expected.get(evidence.governed_evidence_id)
            if legacy_evidence is None or legacy_evidence.evidence_package_reference_id!=evidence.evidence_package_id:raise InvalidReasoningInput("GovernedEvidence exact reference mismatch")
            resolved.append(evidence.governed_evidence_id)
        if set(resolved)!=set(expected):raise InvalidReasoningInput("GovernedEvidence exact lineage cardinality mismatch")
        return state_reference,evidence_references
    def validate(self,input_id,*,actor_id,source_reference):
        value=self._get(input_id);expected=self.calculate_readiness(value.review_status,value.quality,value.evidence,value.applicable_guidelines)
        issues=[]
        if expected is not value.readiness:issues.append("READINESS_MISMATCH")
        if not value.evidence_packages:issues.append("MISSING_EVIDENCE_PACKAGE_REFERENCES")
        if not value.evidence.all:issues.append("MISSING_GOVERNED_EVIDENCE_REFERENCES")
        if not value.applicable_guidelines:issues.append("MISSING_GUIDELINE_REFERENCES")
        result=ReasoningInputValidation(value.input_id,not issues,expected,tuple(issues),self._clock())
        self._event(value,ReasoningAuditType.VALIDATION,actor_id,source_reference,"VALID" if result.valid else "INVALID");return result
    def reconstruct(self,subject_reference,version,*,actor_id="system",source_reference="reasoning-input-history"):
        value=next((item for item in self._repository.history(subject_reference) if item.input_version==version),None)
        if value is None:raise InvalidReasoningInput("reasoning input version does not exist")
        self._event(value,ReasoningAuditType.RECONSTRUCTION,actor_id,source_reference,"RECONSTRUCTED");return value
    def mark_reviewed(self,subject_reference,*,actor_id,source_reference):return self._review(subject_reference,ReasoningReviewStatus.REVIEWED,actor_id,source_reference)
    def approve(self,subject_reference,*,actor_id,source_reference):
        current=self._latest(subject_reference)
        if current.review_status is not ReasoningReviewStatus.REVIEWED:raise InvalidReasoningInput("only reviewed input may be approved")
        return self._review(subject_reference,ReasoningReviewStatus.APPROVED,actor_id,source_reference,ReasoningAuditType.APPROVAL)
    def reject(self,subject_reference,*,actor_id,source_reference):return self._review(subject_reference,ReasoningReviewStatus.REJECTED,actor_id,source_reference,ReasoningAuditType.REJECTION)
    def _review(self,subject,status,actor,source,event_type=ReasoningAuditType.VALIDATION):
        current=self._latest(subject);quality=current.quality
        readiness=self.calculate_readiness(status,quality,current.evidence,current.applicable_guidelines)
        value=replace(current,input_id=self._id(current.input_id,status.value,str(current.input_version+1)),input_version=current.input_version+1,
          previous_input_id=current.input_id,created_at=self._clock(),review_status=status,readiness=readiness)
        self._repository.append(value);self._event(value,event_type,actor,source,status.value);return value
    @staticmethod
    def calculate_readiness(review,quality,evidence,guidelines):
        if review is ReasoningReviewStatus.REJECTED:return ReasoningReadiness.BLOCKED
        if quality.conflicting_data_references:return ReasoningReadiness.CONFLICTING_INPUT
        if quality.missing_data_references or quality.overall_input_completeness<0.8 or not evidence.all or not guidelines:return ReasoningReadiness.INSUFFICIENT_DATA
        if quality.review_required or review in (ReasoningReviewStatus.AUTO_ASSEMBLED,ReasoningReviewStatus.REVIEW_REQUIRED):return ReasoningReadiness.REVIEW_REQUIRED
        return ReasoningReadiness.READY_FOR_REASONING
    def _latest(self,subject):
        value=self._repository.latest(subject)
        if value is None:raise InvalidReasoningInput("reasoning input does not exist")
        return value
    def _get(self,input_id):
        value=self._repository.get(input_id)
        if value is None:raise InvalidReasoningInput("reasoning input does not exist")
        return value
    def _event(self,value,kind,actor,source,decision):
        policy=value.policy_versions[0].policy_version
        event=ReasoningInputAuditEvent(self._id(value.input_id,kind.value,decision),value.subject_reference,value.input_id,kind,self._clock(),actor,source,policy,decision)
        self._audit.append(event)
    @staticmethod
    def _id(*parts):return "ri_"+sha256("|".join(parts).encode()).hexdigest()

class ClinicalReasoningInputQueryService:
    def __init__(self,repository):self._repository=repository
    def get(self,input_id):
        value=self._repository.get(input_id)
        if value is None:raise InvalidReasoningInput("reasoning input does not exist")
        return value
    def latest(self,subject_reference):
        value=self._repository.latest(subject_reference)
        if value is None:raise InvalidReasoningInput("reasoning input does not exist")
        return value
    def reconstruct(self,subject_reference,version):
        value=next((item for item in self._repository.history(subject_reference) if item.input_version==version),None)
        if value is None:raise InvalidReasoningInput("reasoning input version does not exist")
        return value
