from dataclasses import FrozenInstanceError,replace
from datetime import datetime,timezone
import pytest
from jmoraIs.audit_defense import *
from jmoraIs.clinical import *
from tests.test_guideline_engine import ready_input,setup as guideline_setup,evidence,guideline,Lifecycle
from tests.test_orthopedic_intelligence import engine as ortho_setup,view,finding,Query
from tests.test_terminology import concept
NOW=datetime(2026,8,10,tzinfo=timezone.utc)
class Latest:
    def __init__(self,value):self.value=value
    def latest(self,subject):return self.value
def clinical_fact(status="REPORTED"):
    inp=ready_input();return GovernedAuditClinicalFact("clinical-fact-1",inp.patient_clinical_state.reference_id,inp.patient_clinical_state.clinical_state_version,status,("concept-1",),("prov:clinical",))
def setup(*,evidences=None,guidelines=None,facts=None,lifecycle=None,input_value=None):
    inp=input_value or ready_input();term=replace(concept(),canonical_id="concept-1",version=inp.terminology_version)
    evs=tuple(evidences or (evidence(),));gengine,_,_=guideline_setup(guidelines=guidelines,evidences=evs,concepts=(term,));gset=gengine.create_recommendation_set(inp)
    oengine,_,_,_=ortho_setup(view(finding()),evidences=evs,concepts=(term,));oset=oengine.generate(inp)
    repo=InMemoryAuditDefenseRepository();audit=InMemoryAuditDefenseEventAdapter();canonical=InMemoryGovernedDecisionAuditRepository();auth=InMemoryReviewerAuthorizationAdapter((ReviewerIdentity("reviewer",ReviewerRole.SENIOR_REVIEWER),));review=AuthorizedRecommendationReviewService(auth,canonical,ReviewAuthorizationPolicy(),clock=lambda:NOW)
    c=tuple((clinical_fact(),) if facts is None else facts)
    service=AuditDefenseService(InMemoryAuditClinicalStateAdapter({inp.patient_clinical_state.reference_id:c}),Query(evs,"governed_evidence_id"),lifecycle or Lifecycle(),Latest(gset),Latest(oset),Query((term,),"canonical_id"),repo,audit,review,clock=lambda:NOW)
    return service,repo,audit,inp
def test_source_bound_defense_is_immutable_traceable_and_non_actionable():
    service,_,audit,inp=setup();result=service.generate(inp);defense=result.defense
    assert defense.status is DefenseStatus.DRAFT and not defense.externally_actionable
    assert defense.arguments[0].argument_code=="SOURCE_BOUND_TECHNICAL_ARGUMENT"
    assert defense.arguments[0].clinical_support[0].fact_id=="clinical-fact-1"
    assert defense.explainability.supporting_evidence_ids==("governed-1",) and defense.provenance_references
    assert audit.history(result.stream_id)
    with pytest.raises(FrozenInstanceError):defense.status=DefenseStatus.APPROVED_BY_REVIEWER
@pytest.mark.parametrize("invalid",[{},object(),"raw PatientContext","raw EvidencePackage","free audit text"])
def test_only_clinical_reasoning_input_is_accepted(invalid):
    with pytest.raises(AuditDefenseBoundaryRejected):setup()[0].generate(invalid)
def test_supporting_opposing_neutral_and_inconclusive_are_separate_and_traceable():
    ev=evidence(directions=("SUPPORTING","OPPOSING","NEUTRAL","INCONCLUSIVE"));result=setup(evidences=(ev,))[0].generate(ready_input());e=result.defense.explainability
    assert e.supporting_evidence_ids==e.opposing_evidence_ids==e.neutral_evidence_ids==e.inconclusive_evidence_ids==("governed-1",)
    assert result.defense.arguments[0].position is ArgumentPosition.CONFLICTED
    assert result.defense.arguments[0].counterarguments[0].code=="OPPOSING_EVIDENCE_PRESENT"
def test_guideline_support_preserves_governed_identity_strength_review_and_provenance():
    item=setup()[0].generate(ready_input()).defense.arguments[0].guideline_support[0]
    assert item.guideline_id=="guideline-1" and item.guideline_version=="2026.1" and item.strength=="CONDITIONAL_FOR"
    assert item.review_status is HumanReviewStatus.PENDING_REVIEW and item.provenance_references
def test_guideline_conflict_is_exposed_as_limitation_and_counterargument():
    first=guideline();second=guideline("guideline-2","guideline-rec-2",organization="Other",intent=__import__("jmoraIs.guideline_engine",fromlist=["RecommendationIntent"]).RecommendationIntent.AVOID)
    inp=ready_input();inp=replace(inp,applicable_guidelines=inp.applicable_guidelines+(replace(inp.applicable_guidelines[0],reference_id="guideline-2",organization="Other"),))
    result=setup(guidelines=(first,second),input_value=inp)[0].generate(inp)
    assert result.defense.status is DefenseStatus.REVIEW_REQUIRED
    assert any(x.code=="GUIDELINE_CONFLICT" for x in result.defense.arguments[0].limitations)
    assert any(x.code=="GUIDELINE_CONFLICT_PRESENT" for x in result.defense.arguments[0].counterarguments)
def test_missing_conflicting_and_stale_data_are_explicit_limitations():
    base=ready_input();quality=replace(base.quality,missing_data_references=("missing",),conflicting_data_references=("conflict",),stale_data_references=("stale",));inp=replace(base,quality=quality)
    result=setup(input_value=inp)[0].generate(inp);codes={x.code for x in result.defense.arguments[0].limitations}
    assert {"MISSING_CLINICAL_DATA","CONFLICTING_CLINICAL_DATA","STALE_CLINICAL_DATA"}<=codes
    assert result.defense.status is DefenseStatus.REVIEW_REQUIRED
def test_missing_clinical_support_fails_closed_without_inventing_fact():
    result=setup(facts=())[0].generate(ready_input());argument=result.defense.arguments[0]
    assert argument.clinical_support[0].fact_id=="NOT_DOCUMENTED"
    assert any(x.code=="NO_GOVERNED_CLINICAL_FACT" for x in argument.limitations)
def test_epistemic_status_is_preserved_without_diagnostic_promotion():
    item=setup(facts=(clinical_fact("SUSPECTED"),))[0].generate(ready_input()).defense.arguments[0].clinical_support[0]
    assert item.epistemic_status=="SUSPECTED"
def test_inactive_evidence_invalid_terminology_and_unready_input_are_rejected():
    service,_,_,inp=setup(lifecycle=Lifecycle("RETRACTED"))
    with pytest.raises(AuditDefenseBoundaryRejected):service.generate(inp)
    service,_,_,inp=setup();service._terminology=Query((),"canonical_id")
    with pytest.raises(AuditDefenseBoundaryRejected):service.generate(inp)
    with pytest.raises(AuditDefenseBoundaryRejected):setup()[0].generate(replace(ready_input(),readiness=ReasoningReadiness.REVIEW_REQUIRED))
def test_authorized_review_rejection_history_and_no_autonomous_authorization():
    service,repo,_,inp=setup();first=service.generate(inp);approved=service.submit_for_review(first.stream_id,reviewer_id="reviewer",target=HumanReviewStatus.APPROVED_BY_REVIEWER,justification="reviewed")
    assert approved.defense.status is DefenseStatus.APPROVED_BY_REVIEWER and not approved.defense.externally_actionable
    assert service.reconstruct(first.stream_id,1)==first and len(repo.history(first.stream_id))==2
    rejecting,_,_,inp=setup();draft=rejecting.generate(inp);rejected=rejecting.submit_for_review(draft.stream_id,reviewer_id="reviewer",target=HumanReviewStatus.REJECTED_BY_REVIEWER,justification="rejected")
    assert rejected.defense.status is DefenseStatus.REJECTED_BY_REVIEWER
def test_conflicted_defense_cannot_be_approved():
    ev=evidence(directions=("SUPPORTING","OPPOSING"));service,_,_,inp=setup(evidences=(ev,));value=service.generate(inp)
    with pytest.raises(AuditDefenseBoundaryRejected):service.submit_for_review(value.stream_id,reviewer_id="reviewer",target=HumanReviewStatus.APPROVED_BY_REVIEWER,justification="invalid")
def test_repository_is_append_only_and_chain_validated():
    service,repo,_,inp=setup();first=service.generate(inp)
    with pytest.raises(AuditDefenseVersionConflict):repo.append(first)
    with pytest.raises(AuditDefenseVersionConflict):repo.append(replace(first,package_id="forged",version=3,previous_package_id="wrong"))
