from __future__ import annotations
from dataclasses import asdict,replace
from hashlib import sha256
from jmoraIs.appraisal.governed import GovernedEvidence
from jmoraIs.clinical.governed import GovernedClinicalRecommendation,GovernedRecommendationExplanation,HumanReviewStatus
from jmoraIs.guideline_engine.domain import GuidelineRecommendationSet
from jmoraIs.orthopedic_intelligence.domain import OrthopedicAssessmentSet
from jmoraIs.reasoning_input.domain import ClinicalReasoningInput,ReasoningReadiness
from .domain import *

class DocumentValidationGate:
    VERSION="MIP-08-GATE-1";DIRECT=("cpf","email","e-mail","telefone","address","endereço","patient_name","nome completo")
    FORBIDDEN=("diagnóstico confirmado pelo sistema","tratamento indicado pelo sistema","cirurgia indicada pelo sistema","autorização aprovada")
    def __init__(self,*,clock):self._clock=clock
    def validate(self,sections,template):
        issues=[];present={x.section_id for x in sections}
        for required in template.required_sections:
            if required not in present:issues.append(DocumentValidationIssue("REQUIRED_SECTION_MISSING",ValidationSeverity.CRITICAL,required,()))
        allowed=dict(template.allowed_sources)
        for section in sections:
            if section.section_id not in template.section_order:issues.append(DocumentValidationIssue("SECTION_NOT_IN_TEMPLATE",ValidationSeverity.CRITICAL,section.section_id,()))
            for fact in section.facts:
                if not fact.source_reference_id or not fact.provenance_references:issues.append(DocumentValidationIssue("UNSUPPORTED_CLINICAL_CLAIM",ValidationSeverity.CRITICAL,section.section_id,(fact.fact_id,)))
                if fact.source_type not in allowed.get(section.section_id,()):issues.append(DocumentValidationIssue("SOURCE_TYPE_NOT_ALLOWED",ValidationSeverity.CRITICAL,section.section_id,(fact.fact_id,)))
                lowered=fact.statement.casefold()
                if any(token in lowered for token in self.DIRECT):issues.append(DocumentValidationIssue("PRIVACY_VIOLATION",ValidationSeverity.CRITICAL,section.section_id,(fact.fact_id,)))
                if any(token in lowered for token in self.FORBIDDEN):issues.append(DocumentValidationIssue("UNSUPPORTED_MEDICAL_DECISION",ValidationSeverity.CRITICAL,section.section_id,(fact.fact_id,)))
            for citation in section.evidence:
                if citation.verification_status!="VERIFIED" or not citation.canonical_vancouver or not citation.citation_reference_id:issues.append(DocumentValidationIssue("INVALID_CITATION_REFERENCE",ValidationSeverity.CRITICAL,section.section_id,(citation.governed_evidence_id,)))
            for term in section.terminology:
                if term.review_required or term.mapping_status in {"AMBIGUOUS","REVIEW_REQUIRED"} or term.confidence in {"LOW","UNKNOWN"}:issues.append(DocumentValidationIssue("TERMINOLOGY_UNCERTAINTY",ValidationSeverity.WARNING,section.section_id,(term.concept_id,)))
            if any(x.code.startswith("CONFLICT") for x in section.limitations):issues.append(DocumentValidationIssue("UNRESOLVED_CONFLICT",ValidationSeverity.CRITICAL,section.section_id,tuple(r for x in section.limitations for r in x.source_references)))
            if any(x.code=="REQUIRED_INFORMATION_ABSENT" for x in section.limitations):issues.append(DocumentValidationIssue("REQUIRED_INFORMATION_ABSENT",ValidationSeverity.CRITICAL,section.section_id,tuple(r for x in section.limitations for r in x.source_references)))
        return DocumentValidationResult(not any(x.severity is ValidationSeverity.CRITICAL for x in issues),tuple(issues),self._clock(),self.VERSION)

class MedicalDocumentEngine:
    POLICY="MIP-08.1"
    def __init__(self,facts,terminology,evidence,evidence_lifecycle,citations,guidelines,orthopedic,templates,repository,audit,review_service,*,clock):
        self._facts=facts;self._terminology=terminology;self._evidence=evidence;self._lifecycle=evidence_lifecycle;self._citations=citations;self._guidelines=guidelines;self._orthopedic=orthopedic;self._templates=templates;self._repository=repository;self._audit=audit;self._review=review_service;self._clock=clock;self._gate=DocumentValidationGate(clock=clock)
    def generate(self,value,document_type,*,actor_id="document-engine",template_version=None,guideline_set_reference=None,orthopedic_set_reference=None):
        self._guard(value,document_type);template=self._templates.get(document_type,template_version)
        if not isinstance(template,DocumentTemplate):raise DocumentBoundaryRejected("governed document template is required")
        sources={source for _,allowed in template.allowed_sources for source in allowed};clinical=self._clinical_facts(value) if SourceType.PATIENT_CLINICAL_STATE in sources else ();evidence=self._evidence_refs(value) if SourceType.GOVERNED_EVIDENCE in sources else ();guideline_source,guidelines=self._guideline_refs(value,guideline_set_reference) if SourceType.GUIDELINE_RECOMMENDATION_SET in sources else (None,());orthopedic_source=self._orthopedic_source(value,document_type,orthopedic_set_reference);orthopedic=self._orthopedic_facts(orthopedic_source,document_type);terms=self._terminology_refs(clinical+orthopedic,value.terminology_version)
        sections=self._sections(template,clinical,orthopedic,evidence,guidelines,terms,value)
        validation=self._gate.validate(sections,template);status=DocumentStatus.DRAFT if validation.valid else DocumentStatus.REVIEW_REQUIRED
        stream=self._id(value.subject_reference,document_type.value);latest=self._repository.latest(stream);version=1 if latest is None else latest.version+1
        if latest is not None:self._audit_event(latest,DocumentAuditType.SUPERSESSION,actor_id,"SUPERSEDED",(latest.version_id,))
        document_id=self._id(stream,str(version),template.template_version)
        manifest=self._manifest(sections,template);ortho_valid=isinstance(orthopedic_source,OrthopedicAssessmentSet) and orthopedic_source.assessment.reasoning_input_id==value.input_id
        document=MedicalDocument(document_id,document_type,value.subject_reference,value.input_id,value.input_version,value.patient_clinical_state.reference_id,value.patient_clinical_state.clinical_state_version,orthopedic_source.set_id if ortho_valid else None,orthopedic_source.set_version if ortho_valid else None,(value.terminology_version,),tuple(x.governed_evidence_id for x in evidence),tuple(x.recommendation_id for x in guidelines),tuple(sorted({x.policy_version for x in value.policy_versions}|{self.POLICY})),template.template_id,template.template_version,sections,status,HumanReviewStatus.PENDING_REVIEW,validation,manifest,self._clock(),tuple(sorted({x.reference_id for x in value.provenance_references}|{r for s in sections for r in s.provenance_references})),False,guideline_set_reference if guideline_source is not None else None,orthopedic_set_reference if ortho_valid else None)
        result=MedicalDocumentVersion(document_id,stream,version,latest.version_id if latest else None,document,(),None,None,self._clock());self._repository.append(result)
        self._audit_event(result,DocumentAuditType.GENERATION,actor_id,status.value,(document_id,))
        self._audit_issues(result,validation,actor_id)
        if evidence:self._audit_event(result,DocumentAuditType.CITATION_INCLUDED,actor_id,"CANONICAL_CITATIONS",tuple(x.governed_evidence_id for x in evidence))
        if guidelines:self._audit_event(result,DocumentAuditType.GUIDELINE_INCLUDED,actor_id,"GOVERNED_GUIDELINES",tuple(x.recommendation_id for x in guidelines))
        return result
    def generate_controlled(self,value,document_type,*,guideline_set_reference,orthopedic_set_reference,actor_id="document-engine",template_version=None):
        if guideline_set_reference is None or orthopedic_set_reference is None:raise DocumentBoundaryRejected("controlled-pilot document generation requires exact owner-issued guideline and orthopedic references")
        return self.generate(value,document_type,actor_id=actor_id,template_version=template_version,guideline_set_reference=guideline_set_reference,orthopedic_set_reference=orthopedic_set_reference)
    def submit_for_review(self,stream_id,*,reviewer_id,target,justification,generated_by="document-engine"):
        current=self._repository.latest(stream_id)
        if current is None:raise DocumentBoundaryRejected("document does not exist")
        if target is HumanReviewStatus.APPROVED_BY_REVIEWER and not current.document.validation.valid:raise DocumentBoundaryRejected("invalid document cannot be approved")
        d=current.document
        proxy=GovernedClinicalRecommendation(d.document_id,d.document_id,"Governed medical document",1,0,0,d.governed_evidence_ids,(),d.provenance_references,(),d.policy_versions,GovernedRecommendationExplanation(d.provenance_references,(),(),(),(),(),tuple(x.code for x in d.validation.issues),tuple(x.code for s in d.sections for x in s.limitations),(),0,0,0,0,d.review_status),d.review_status,False)
        reviewed=self._review.transition(case_id=stream_id,recommendation=proxy,target=target,reviewer_id=reviewer_id,justification=justification,generated_by=generated_by)
        status=DocumentStatus.APPROVED_BY_REVIEWER if target is HumanReviewStatus.APPROVED_BY_REVIEWER else (DocumentStatus.REJECTED_BY_REVIEWER if target is HumanReviewStatus.REJECTED_BY_REVIEWER else DocumentStatus.UNDER_REVIEW)
        version=current.version+1;newdoc=replace(d,document_id=self._id(d.document_id,str(version),target.value),status=status,review_status=reviewed.review_status,externally_valid=False,generated_at=self._clock());result=MedicalDocumentVersion(newdoc.document_id,stream_id,version,current.version_id,newdoc,(),reviewer_id,justification,self._clock());self._repository.append(result);self._audit_event(result,DocumentAuditType.REVIEW_TRANSITION,reviewer_id,target.value,(current.version_id,));return result
    def correct(self,stream_id,sections,*,reviewer_id,justification):
        current=self._repository.latest(stream_id)
        if current is None or not justification.strip():raise DocumentBoundaryRejected("document and correction justification are required")
        template=self._templates.get(current.document.document_type,current.document.template_version);sections=tuple(sections);validation=self._gate.validate(sections,template)
        version=current.version+1;doc=replace(current.document,document_id=self._id(current.document.document_id,str(version),"correction"),sections=sections,status=DocumentStatus.REVIEW_REQUIRED,review_status=HumanReviewStatus.PENDING_REVIEW,validation=validation,traceability=self._manifest(sections,template),generated_at=self._clock(),externally_valid=False)
        changed=tuple(x.section_id for x in sections if x not in current.document.sections);result=MedicalDocumentVersion(doc.document_id,stream_id,version,current.version_id,doc,changed,reviewer_id,justification,self._clock());self._repository.append(result);self._audit_event(result,DocumentAuditType.CORRECTION,reviewer_id,"CORRECTED",changed);return result
    def reconstruct(self,stream_id,version):
        result=next((x for x in self._repository.history(stream_id) if x.version==version),None)
        if result is None:raise DocumentBoundaryRejected("document version not found")
        return result
    def render(self,value,format):
        if not isinstance(value,MedicalDocumentVersion):raise DocumentBoundaryRejected("only persisted MedicalDocumentVersion can be rendered")
        if format=="json":content=asdict(value.document)
        elif format in {"text","markdown"}:
            lines=[]
            for section in value.document.sections:
                lines.append(("## " if format=="markdown" else "")+section.title)
                lines.extend(f"[{x.epistemic_status.value}] {x.statement}" for x in section.facts)
                lines.extend(x.canonical_vancouver for x in section.evidence)
                lines.extend(f"{x.marker.value}: {x.code}" for x in section.limitations)
            content="\n".join(lines)
        else:raise DocumentBoundaryRejected("supported formats are json, text, and markdown")
        return RenderedDocument(value.document.document_id,format,content,value.document.traceability)
    def _guard(self,value,document_type):
        if not isinstance(value,ClinicalReasoningInput):raise DocumentBoundaryRejected("only ClinicalReasoningInput is accepted")
        if value.readiness is not ReasoningReadiness.READY_FOR_REASONING or value.quality.review_required:raise DocumentBoundaryRejected("reasoning input is not ready")
        if not isinstance(document_type,DocumentType):raise DocumentBoundaryRejected("canonical DocumentType is required")
    def _clinical_facts(self,value):
        result=self._facts.facts(value.patient_clinical_state.reference_id)
        if not isinstance(result,tuple) or any(not isinstance(x,DocumentFactReference) or x.source_type is not SourceType.PATIENT_CLINICAL_STATE for x in result):raise DocumentBoundaryRejected("clinical facts must come from governed state references")
        return result
    def _evidence_refs(self,value):
        result=[]
        for ref in value.evidence.all:
            evidence=self._evidence.get(ref.reference_id);citation=self._citations.get(ref.reference_id)
            if not isinstance(evidence,GovernedEvidence) or self._lifecycle.current_status(evidence)!="ACTIVE" or not isinstance(citation,DocumentEvidenceReference) or citation.governed_evidence_id!=evidence.governed_evidence_id or citation.evidence_package_id!=evidence.evidence_package_id:raise DocumentBoundaryRejected("active GovernedEvidence with canonical citation is required")
            result.append(citation)
        return tuple(result)
    def _guideline_refs(self,value,reference):
        if reference is None:
            source=self._guidelines.latest(value.subject_reference)
        else:
            source=self._guidelines.get_exact(reference)
        if not isinstance(source,GuidelineRecommendationSet) or source.reasoning_input_id!=value.input_id:raise DocumentBoundaryRejected("governed guideline set is required")
        if reference is not None and (source.set_id!=reference.set_id or source.set_version!=reference.set_version or source.subject_reference!=value.subject_reference or source.policy_version!=reference.policy_version):raise DocumentBoundaryRejected("exact guideline-set lineage mismatch")
        allowed={x.reference_id for x in value.applicable_guidelines};result=[]
        for x in source.recommendations:
            if x.guideline_id not in allowed:raise DocumentBoundaryRejected("guideline bypass detected")
            result.append(DocumentGuidelineReference(x.recommendation_id,x.guideline_id,x.explanation.organization,x.guideline_version,x.explanation.strength.name,x.review_status,tuple(c.conflict_id for c in x.explanation.conflicts),x.explanation.limitations,x.provenance_references))
        return source,tuple(result)
    def _orthopedic_source(self,value,document_type,reference):
        if document_type not in {DocumentType.ORTHOPEDIC_ASSESSMENT_REPORT,DocumentType.PROCEDURE_JUSTIFICATION_DRAFT,DocumentType.AUDIT_SUPPORT_DRAFT}:return None
        source=self._orthopedic.get_exact(reference) if reference is not None else self._orthopedic.latest(value.subject_reference)
        if not isinstance(source,OrthopedicAssessmentSet) or source.assessment.reasoning_input_id!=value.input_id:raise DocumentBoundaryRejected("governed orthopedic assessment is required")
        if reference is not None and (source.set_id!=reference.set_id or source.set_version!=reference.set_version or source.subject_reference!=value.subject_reference or source.assessment.policy_version!=reference.policy_version):raise DocumentBoundaryRejected("exact orthopedic-set lineage mismatch")
        return source
    def _orthopedic_facts(self,source,document_type):
        if document_type not in {DocumentType.ORTHOPEDIC_ASSESSMENT_REPORT,DocumentType.PROCEDURE_JUSTIFICATION_DRAFT,DocumentType.AUDIT_SUPPORT_DRAFT}:return ()
        facts=[]
        for joint in source.assessment.joints:
            for problem in joint.problems:
                status={"SUSPECTED":FactEpistemicStatus.FACT_SUSPECTED,"CONFIRMED_BY_SOURCE":FactEpistemicStatus.FACT_CONFIRMED}.get(problem.status.value,FactEpistemicStatus.FACT_OBSERVED)
                facts.append(DocumentFactReference(problem.problem_id,f"{joint.joint.value} {joint.laterality.value}: {problem.status.value}",status,SourceType.ORTHOPEDIC_ASSESSMENT_SET,source.set_id,str(source.set_version),problem.terminology_concept_ids,source.assessment.provenance_references))
        return tuple(facts)
    def _terminology_refs(self,facts,version):
        result=[]
        for identifier in sorted({x for fact in facts for x in fact.terminology_reference_ids}):
            item=self._terminology.get(identifier)
            if not isinstance(item,DocumentTerminologyReference) or item.version!=version:raise DocumentBoundaryRejected("governed terminology reference is required")
            result.append(item)
        return tuple(result)
    def _sections(self,template,clinical,orthopedic,evidence,guidelines,terms,value):
        sections=[]
        for order,identifier in enumerate(template.section_order,1):
            allowed=dict(template.allowed_sources).get(identifier,());facts=clinical if SourceType.PATIENT_CLINICAL_STATE in allowed else ();facts+=orthopedic if SourceType.ORTHOPEDIC_ASSESSMENT_SET in allowed else ()
            ev=evidence if SourceType.GOVERNED_EVIDENCE in allowed else ();gl=guidelines if SourceType.GUIDELINE_RECOMMENDATION_SET in allowed else ();tm=terms if SourceType.TERMINOLOGY in allowed else ()
            limitations=[]
            if identifier!="limitations" and not facts and not ev and not gl:limitations.append(DocumentLimitation("REQUIRED_INFORMATION_ABSENT",MissingMarker.NOT_DOCUMENTED,identifier,(value.patient_clinical_state.reference_id,)))
            limitations.extend(DocumentLimitation("CONFLICTING_INPUT",MissingMarker.REVIEW_REQUIRED,identifier,(x,)) for x in value.quality.conflicting_data_references)
            provenance=tuple(sorted({r for x in facts for r in x.provenance_references}|{r for x in ev for r in x.provenance_references}|{r for x in gl for r in x.provenance_references}))
            sections.append(DocumentSection(identifier,identifier.replace("_"," ").title(),order,allowed,tuple(facts),tuple(ev),tuple(gl),tuple(tm),tuple(limitations),provenance))
        return tuple(sections)
    def _manifest(self,sections,template):
        entries=[]
        for s in sections:
            refs=tuple(x.source_reference_id for x in s.facts)+tuple(x.governed_evidence_id for x in s.evidence)+tuple(x.recommendation_id for x in s.guidelines)
            entries.append(TraceabilityEntry(s.section_id,refs,tuple(x.concept_id for x in s.terminology),template.policy_version,template.template_version))
        return TraceabilityManifest(tuple(entries),self._clock())
    def _audit_issues(self,value,validation,actor):
        mapping={"TERMINOLOGY_UNCERTAINTY":DocumentAuditType.TERMINOLOGY_UNCERTAINTY,"UNRESOLVED_CONFLICT":DocumentAuditType.CONFLICTING_DATA,"REQUIRED_SECTION_MISSING":DocumentAuditType.MISSING_DATA,"REQUIRED_INFORMATION_ABSENT":DocumentAuditType.MISSING_DATA}
        for issue in validation.issues:self._audit_event(value,mapping.get(issue.code,DocumentAuditType.VALIDATION_FAILURE),actor,issue.code,((issue.section_id,) if issue.section_id else ())+issue.reference_ids)
    def _audit_event(self,value,kind,actor,decision,refs):self._audit.append(DocumentAuditEvent(self._id(value.version_id,kind.value,decision,*refs),value.document_stream_id,value.version_id,kind,self._clock(),actor,decision,tuple(refs),self.POLICY))
    @staticmethod
    def _id(*parts):return "doc_"+sha256("|".join(parts).encode()).hexdigest()

class DeterministicDocumentRenderer:
    def __init__(self,engine):self._engine=engine
    def render_json(self,value):return self._engine.render(value,"json")
    def render_text(self,value):return self._engine.render(value,"text")
    def render_markdown(self,value):return self._engine.render(value,"markdown")
