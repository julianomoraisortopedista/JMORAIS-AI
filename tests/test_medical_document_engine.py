from dataclasses import FrozenInstanceError,replace
from datetime import datetime,timezone
import pytest
from jmoraIs.medical_documents import *
from jmoraIs.clinical import *
from tests.test_guideline_engine import ready_input,setup as guideline_setup,evidence,Lifecycle
from tests.test_orthopedic_intelligence import engine as ortho_setup,view,finding,Query,Guidelines
NOW=datetime(2026,8,10,tzinfo=timezone.utc)
class Latest:
    def __init__(self,value):self.value=value
    def latest(self,subject):return self.value
def fact(statement="Pain reported",status=FactEpistemicStatus.FACT_REPORTED,concepts=("concept-1",)):
    return DocumentFactReference("fact-1",statement,status,SourceType.PATIENT_CLINICAL_STATE,"state-1","1",concepts,("prov:fact",))
def citation(status="VERIFIED",text="Smith A. Governed article. Journal. 2026;1:1-2."):
    return DocumentEvidenceReference("governed-1","package-1","33522354","10.1000/test",status,text,"citation:verified",("prov:citation",))
def term(**changes):
    values=dict(concept_id="concept-1",display_name="Pain",original_term="pain",version=ready_input().terminology_version,mapping_status="MAPPED",confidence="HIGH",review_required=False,provenance_references=("prov:term",));values.update(changes);return DocumentTerminologyReference(**values)
def setup(*,facts=None,citations=None,terms=None,input_value=None,citation_port=None,evidence_port=None):
    inp=input_value or ready_input();gengine,_,_=guideline_setup();gset=gengine.create_recommendation_set(inp)
    oengine,_,_,_=ortho_setup(view(finding()));oset=oengine.generate(inp)
    repo=InMemoryMedicalDocumentRepository();audit=InMemoryDocumentAuditAdapter();canonical=InMemoryGovernedDecisionAuditRepository();auth=InMemoryReviewerAuthorizationAdapter((ReviewerIdentity("reviewer",ReviewerRole.SENIOR_REVIEWER),));review=AuthorizedRecommendationReviewService(auth,canonical,ReviewAuthorizationPolicy(),clock=lambda:NOW)
    f=tuple(facts if facts is not None else (fact(),));c=tuple(citations if citations is not None else (citation(),));t=tuple(terms if terms is not None else (term(),))
    evidence_query=evidence_port or Query((evidence(),),"governed_evidence_id")
    citation_query=citation_port or InMemoryReferenceQueryAdapter(c,"governed_evidence_id")
    engine=MedicalDocumentEngine(InMemoryFactQueryAdapter({inp.patient_clinical_state.reference_id:f}),InMemoryReferenceQueryAdapter(t,"concept_id"),evidence_query,Lifecycle(),citation_query,Latest(gset),Latest(oset),InMemoryDocumentTemplateRepository(canonical_templates()),repo,audit,review,clock=lambda:NOW)
    return engine,repo,audit,inp

@pytest.mark.parametrize("kind",tuple(DocumentType))
def test_all_document_types_are_versioned_governed_drafts(kind):
    engine,_,audit,inp=setup();result=engine.generate(inp,kind)
    assert result.document.document_type is kind and result.document.pseudonymous_patient_id.startswith("pt_")
    assert result.document.template_version=="1.0" and not result.document.externally_valid
    assert audit.history(result.document_stream_id)
    with pytest.raises(FrozenInstanceError):result.document.status=DocumentStatus.APPROVED_BY_REVIEWER

@pytest.mark.parametrize("invalid",[{},object(),"raw PatientContext","raw EvidencePackage","free text"])
def test_only_canonical_reasoning_input_is_accepted(invalid):
    with pytest.raises(DocumentBoundaryRejected):setup()[0].generate(invalid,DocumentType.CLINICAL_REPORT)

def test_missing_data_is_explicit_without_filler():
    engine,_,_,inp=setup(facts=());result=engine.generate(inp,DocumentType.CLINICAL_REPORT);rendered=engine.render(result,"text")
    assert "NOT_DOCUMENTED" in rendered.content and "REQUIRED_INFORMATION_ABSENT" in rendered.content

def test_suspected_and_inferred_facts_are_never_promoted():
    values=(fact("Suspected finding",FactEpistemicStatus.FACT_SUSPECTED),replace(fact(),fact_id="fact-2",statement="Inferred finding",epistemic_status=FactEpistemicStatus.FACT_INFERRED))
    result=setup(facts=values)[0].generate(ready_input(),DocumentType.CLINICAL_REPORT)
    rendered=setup(facts=values)[0] if False else result
    assert [x.epistemic_status for x in rendered.document.sections[0].facts]==[FactEpistemicStatus.FACT_SUSPECTED,FactEpistemicStatus.FACT_INFERRED]

@pytest.mark.parametrize("statement",["Diagnóstico confirmado pelo sistema","Tratamento indicado pelo sistema","Cirurgia indicada pelo sistema","Autorização aprovada"])
def test_fabricated_medical_decisions_fail_validation(statement):
    engine,_,_,inp=setup(facts=(fact(statement),));result=engine.generate(inp,DocumentType.CLINICAL_REPORT)
    assert not result.document.validation.valid and result.document.status is DocumentStatus.REVIEW_REQUIRED
    assert any(x.code=="UNSUPPORTED_MEDICAL_DECISION" for x in result.document.validation.issues)

def test_orthopedic_report_is_structured_and_does_not_indicate_surgery():
    engine,_,_,inp=setup();result=engine.generate(inp,DocumentType.ORTHOPEDIC_ASSESSMENT_REPORT)
    ortho=next(x for x in result.document.sections if x.section_id=="orthopedic")
    assert ortho.facts and ortho.facts[0].source_type is SourceType.ORTHOPEDIC_ASSESSMENT_SET
    assert "indicated" not in ortho.facts[0].statement.casefold()

def test_evidence_summary_uses_only_canonical_verified_vancouver():
    engine,_,audit,inp=setup();result=engine.generate(inp,DocumentType.EVIDENCE_SUMMARY);section=result.document.sections[0]
    assert section.evidence[0].canonical_vancouver==citation().canonical_vancouver
    assert section.evidence[0].citation_reference_id=="citation:verified"
    assert any(x.event_type is DocumentAuditType.CITATION_INCLUDED for x in audit.history(result.document_stream_id))

def test_actual_document_citation_path_accepts_canonical_scientific_projection():
    from jmoraIs.medical_documents import CanonicalDocumentCitationAdapter
    from tests.test_scientific_citation_persistence import setup as scientific_setup
    article,_,_,_,package,vancouver,_,scientific=scientific_setup();scientific.issue(package_id=package.package_id,article=article,vancouver_reference=vancouver)
    governed=replace(evidence(),evidence_package_id=package.package_id)
    evidence_query=Query((governed,),"governed_evidence_id")
    adapter=CanonicalDocumentCitationAdapter(evidence_query,scientific)
    result=setup(citation_port=adapter,evidence_port=evidence_query)[0].generate(ready_input(),DocumentType.EVIDENCE_SUMMARY)
    projected=result.document.sections[0].evidence[0]
    assert projected.canonical_vancouver==vancouver.rendered_text
    assert projected.vancouver_citation_id==vancouver.citation_id and projected.evidence_package_id==package.package_id

@pytest.mark.parametrize("bad",[replace(citation(),verification_status="PARTIALLY_VERIFIED"),replace(citation(),canonical_vancouver=""),replace(citation(),citation_reference_id="")])
def test_invalid_or_fabricated_citation_is_rejected_by_gate(bad):
    engine,_,_,inp=setup(citations=(bad,));result=engine.generate(inp,DocumentType.EVIDENCE_SUMMARY)
    assert not result.document.validation.valid and any(x.code=="INVALID_CITATION_REFERENCE" for x in result.document.validation.issues)

def test_guideline_summary_preserves_governed_strength_version_review_and_provenance():
    result=setup()[0].generate(ready_input(),DocumentType.GUIDELINE_SUMMARY);item=result.document.sections[0].guidelines[0]
    assert item.guideline_version=="2026.1" and item.strength=="CONDITIONAL_FOR" and item.provenance_references

def test_terminology_uncertainty_is_surfaced():
    ambiguous=term(mapping_status="AMBIGUOUS",confidence="LOW",review_required=True);result=setup(terms=(ambiguous,))[0].generate(ready_input(),DocumentType.CLINICAL_REPORT)
    assert any(x.code=="TERMINOLOGY_UNCERTAINTY" for x in result.document.validation.issues)

def test_privacy_violation_is_detected_and_approval_blocked():
    engine,_,_,inp=setup(facts=(fact("CPF 123.456.789-00"),));result=engine.generate(inp,DocumentType.CLINICAL_REPORT)
    assert any(x.code=="PRIVACY_VIOLATION" for x in result.document.validation.issues)
    with pytest.raises(DocumentBoundaryRejected):engine.submit_for_review(result.document_stream_id,reviewer_id="reviewer",target=HumanReviewStatus.APPROVED_BY_REVIEWER,justification="review")

def test_conflict_is_explicit_and_blocks_approval():
    inp=replace(ready_input(),quality=replace(ready_input().quality,conflicting_data_references=("conflict-1",)))
    engine,_,_,_=setup(input_value=inp);result=engine.generate(inp,DocumentType.CLINICAL_REPORT)
    assert any(x.code=="UNRESOLVED_CONFLICT" for x in result.document.validation.issues)
    with pytest.raises(DocumentBoundaryRejected):engine.submit_for_review(result.document_stream_id,reviewer_id="reviewer",target=HumanReviewStatus.APPROVED_BY_REVIEWER,justification="review")

def test_traceability_manifest_and_renderers_are_deterministic():
    engine,_,_,inp=setup();result=engine.generate(inp,DocumentType.ORTHOPEDIC_ASSESSMENT_REPORT)
    assert result.document.traceability.entries and all(x.template_version=="1.0" for x in result.document.traceability.entries)
    assert engine.render(result,"json").content["document_id"]==result.document.document_id
    assert engine.render(result,"text").content==engine.render(result,"text").content
    assert "## " in engine.render(result,"markdown").content
    with pytest.raises(DocumentBoundaryRejected):engine.render(result,"pdf")

def test_authorized_review_rejection_correction_and_reconstruction_are_append_only():
    engine,repo,audit,inp=setup();first=engine.generate(inp,DocumentType.CLINICAL_REPORT)
    approved=engine.submit_for_review(first.document_stream_id,reviewer_id="reviewer",target=HumanReviewStatus.APPROVED_BY_REVIEWER,justification="reviewed")
    assert approved.document.status is DocumentStatus.APPROVED_BY_REVIEWER and not approved.document.externally_valid
    corrected=engine.correct(first.document_stream_id,approved.document.sections,reviewer_id="reviewer",justification="source correction")
    assert corrected.version==3 and corrected.previous_version_id==approved.version_id and corrected.document.status is DocumentStatus.REVIEW_REQUIRED
    assert engine.reconstruct(first.document_stream_id,1)==first and len(repo.history(first.document_stream_id))==3
    assert any(x.event_type is DocumentAuditType.CORRECTION for x in audit.history(first.document_stream_id))
    rejecting,_,_,inp=setup();draft=rejecting.generate(inp,DocumentType.MEDICAL_SUMMARY);rejected=rejecting.submit_for_review(draft.document_stream_id,reviewer_id="reviewer",target=HumanReviewStatus.REJECTED_BY_REVIEWER,justification="rejected")
    assert rejected.document.status is DocumentStatus.REJECTED_BY_REVIEWER

def test_repository_rejects_duplicate_and_broken_history():
    engine,repo,_,inp=setup();first=engine.generate(inp,DocumentType.MEDICAL_SUMMARY)
    with pytest.raises(DocumentVersionConflict):repo.append(first)
    with pytest.raises(DocumentVersionConflict):repo.append(replace(first,version_id="forged",version=3,previous_version_id="wrong"))
