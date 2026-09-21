from dataclasses import FrozenInstanceError,replace
from datetime import date,datetime,timezone,timedelta
import pytest
from jmoraIs.guideline_engine import *
from jmoraIs.appraisal.domain import RecommendationStrength
from jmoraIs.appraisal.governed import GovernedEvidence
from jmoraIs.clinical import *
from jmoraIs.reasoning_input import *
from jmoraIs.terminology import *
from tests.test_reasoning_input import draft
from tests.test_terminology import concept
NOW=datetime(2026,8,10,tzinfo=timezone.utc)
class EvidenceQuery:
    def __init__(self,items):self.items={item.governed_evidence_id:item for item in items}
    def get(self,identifier):return self.items.get(identifier)
class Lifecycle:
    def __init__(self,status="ACTIVE"):self.status=status
    def current_status(self,evidence):return self.status
def evidence(identifier="governed-1",directions=("SUPPORTING",),strength="CONDITIONAL_FOR"):
    return GovernedEvidence(identifier,"package-1","appraisal-1","RANDOMIZED_CONTROLLED_TRIAL","HIGH",.9,strength,("ADULT",),"Society","VALID",None,None,None,(),directions,("evidence:prov",),("ledger:1",),"MIP-04-v1","ST-13.1",(),NOW,"hash")
def guideline(identifier="guideline-1",recommendation_id="guideline-rec-1",**changes):
    values=dict(guideline_recommendation_id=recommendation_id,guideline_id=identifier,guideline_version="2026.1",organization="Society",statement="Governed recommendation statement",intent=RecommendationIntent.CONSIDER,strength=RecommendationStrength.CONDITIONAL_FOR,evidence_certainty="MODERATE",methodological_quality="HIGH",authority_weight=.9,applicability=ApplicabilityCriteria(("ADULT",),()),governed_evidence_ids=("governed-1",),publication_date=date(2026,1,1),effective_date=date(2026,1,1),expiration_date=date(2027,1,1),withdrawn_at=None,superseded_by=None,appraisal_approved=True,appraisal_version="ST-13.1",terminology_version="terms-2026.1",policy_version="MIP-04-v1",provenance_references=("guideline:prov",));values.update(changes);return GovernedGuidelineRecommendation(**values)
def ready_input():
    repo=InMemoryClinicalReasoningInputRepository();audit=InMemoryReasoningInputAuditAdapter();service=ClinicalReasoningInputService(repo,audit,clock=lambda:NOW)
    first=service.build(draft(),actor_id="system",source_reference="assembly");return service.mark_reviewed(first.subject_reference,actor_id="physician",source_reference="review")
def setup(guidelines=None,evidences=None,lifecycle=None,concepts=()):
    repo=InMemoryRecommendationRepository();audit=InMemoryRecommendationAuditAdapter();canonical_audit=InMemoryGovernedDecisionAuditRepository()
    auth=InMemoryReviewerAuthorizationAdapter((ReviewerIdentity("reviewer",ReviewerRole.SENIOR_REVIEWER),))
    review=AuthorizedRecommendationReviewService(auth,canonical_audit,ReviewAuthorizationPolicy(),clock=lambda:NOW)
    engine=GuidelineRecommendationEngine(InMemoryGuidelineQueryAdapter(guidelines or (guideline(),)),EvidenceQuery(evidences or (evidence(),)),lifecycle or Lifecycle(),InMemoryGovernedTerminologyConceptQueryAdapter(concepts),repo,audit,review,clock=lambda:NOW)
    return engine,repo,audit
def test_valid_guideline_is_applicable_explainable_and_not_actionable():
    engine,_,audit=setup();result=engine.create_recommendation_set(ready_input())
    assert result.readiness is RecommendationReadiness.READY_FOR_HUMAN_REVIEW
    item=result.recommendations[0];assert item.explanation.strength is RecommendationStrength.CONDITIONAL_FOR
    assert item.explanation.basis.supporting==("governed-1",) and item.explanation.basis.opposing==()
    assert item.explanation.guideline_id=="guideline-1" and not item.externally_actionable
    assert item.explanation.evidence_certainty=="MODERATE" and item.explanation.strength is RecommendationStrength.CONDITIONAL_FOR
    assert audit.history(result.subject_reference)
    with pytest.raises(FrozenInstanceError):item.rank=5
@pytest.mark.parametrize("invalid",[{},object(),"raw PatientContext","raw ClinicalState","raw EvidencePackage"])
def test_only_clinical_reasoning_input_is_accepted(invalid):
    with pytest.raises(GuidelineBoundaryRejected):setup()[0].create_recommendation_set(invalid)
def test_unready_and_incomplete_input_fail_closed():
    value=replace(ready_input(),readiness=ReasoningReadiness.REVIEW_REQUIRED)
    with pytest.raises(GuidelineBoundaryRejected):setup()[0].create_recommendation_set(value)
def test_no_applicable_expired_withdrawn_superseded_and_incomplete_guidelines_are_excluded():
    cases=(guideline(identifier="other"),guideline(expiration_date=date(2025,1,1)),guideline(withdrawn_at=date(2026,1,1)),guideline(superseded_by="new"),guideline(appraisal_approved=False),guideline(terminology_version="old"))
    for item in cases:
        result=setup(guidelines=(item,))[0].create_recommendation_set(ready_input())
        assert result.readiness is RecommendationReadiness.NO_APPLICABLE_GUIDELINE and not result.recommendations
def test_material_terminology_ambiguity_blocks_and_governed_concept_matches():
    item=concept();ambiguous=replace(item,status=TerminologyStatus.UNKNOWN)
    with pytest.raises(GuidelineBoundaryRejected):setup(concepts=(ambiguous,))[0].create_recommendation_set(ready_input(),(ambiguous.canonical_id,))
    rule=guideline(applicability=ApplicabilityCriteria(("ADULT",),(item.canonical_id,)))
    result=setup(guidelines=(rule,),concepts=(item,))[0].create_recommendation_set(ready_input(),(item.canonical_id,))
    assert result.recommendations[0].explanation.applicability.matched_concept_ids==(item.canonical_id,)
def test_unknown_contraindication_is_preserved_without_inference():
    rule=guideline(applicability=ApplicabilityCriteria(("ADULT",),(),("contra-1",)))
    result=setup(guidelines=(rule,))[0].create_recommendation_set(ready_input())
    assert result.recommendations[0].explanation.contraindication_status is ContraindicationStatus.UNKNOWN
def test_supporting_opposing_neutral_and_inconclusive_are_separate():
    ev=evidence(directions=("SUPPORTING","OPPOSING","NEUTRAL","INCONCLUSIVE"));item=setup(evidences=(ev,))[0].create_recommendation_set(ready_input()).recommendations[0]
    assert all(getattr(item.explanation.basis,name)==("governed-1",) for name in ("supporting","opposing","neutral","inconclusive"))
def test_critical_guideline_conflict_is_explicit_and_blocks_approval():
    first=guideline();second=guideline("guideline-2","guideline-rec-2",organization="Other Society",intent=RecommendationIntent.AVOID,strength=RecommendationStrength.STRONG_AGAINST)
    input_value=ready_input();second_ref=replace(input_value.applicable_guidelines[0],reference_id="guideline-2",organization="Other Society")
    input_value=replace(input_value,applicable_guidelines=input_value.applicable_guidelines+(second_ref,))
    engine,_,_=setup(guidelines=(first,second));result=engine.create_recommendation_set(input_value)
    assert result.readiness is RecommendationReadiness.CONFLICTING_GUIDANCE
    assert any(conflict.severity is ConflictSeverity.CRITICAL_CONFLICT for conflict in result.recommendations[0].explanation.conflicts)
    with pytest.raises(GuidelineBoundaryRejected):engine.submit_for_human_review(result.subject_reference,reviewer_id="reviewer",target=HumanReviewStatus.APPROVED_BY_REVIEWER,justification="reviewed")
def test_ranking_is_deterministic_explicit_and_strength_is_not_evidence_certainty():
    first=guideline();second=guideline("guideline-2","guideline-rec-2",organization="Society",authority_weight=.5,strength=RecommendationStrength.STRONG_FOR,evidence_certainty="LOW")
    value=ready_input();value=replace(value,applicable_guidelines=value.applicable_guidelines+(replace(value.applicable_guidelines[0],reference_id="guideline-2"),))
    result=setup(guidelines=(first,second))[0].create_recommendation_set(value)
    assert [item.rank for item in result.recommendations]==[1,2] and all(item.confidence.policy_version=="MIP-06-CONFIDENCE-1" for item in result.recommendations)
def test_canonical_reviewer_approval_rejection_and_invalid_transition():
    engine,repo,audit=setup();generated=engine.create_recommendation_set(ready_input())
    approved=engine.submit_for_human_review(generated.subject_reference,reviewer_id="reviewer",target=HumanReviewStatus.APPROVED_BY_REVIEWER,justification="governed review")
    assert approved.recommendations[0].externally_actionable
    with pytest.raises(ReviewTransitionRejected):engine.submit_for_human_review(generated.subject_reference,reviewer_id="reviewer",target=HumanReviewStatus.APPROVED_BY_REVIEWER,justification="again")
    assert len(repo.history(generated.subject_reference))==2 and audit.history(generated.subject_reference)[-1].event_type is RecommendationAuditType.HUMAN_REVIEW
    rejecting,_,_=setup();pending=rejecting.create_recommendation_set(ready_input())
    rejected=rejecting.submit_for_human_review(pending.subject_reference,reviewer_id="reviewer",target=HumanReviewStatus.REJECTED_BY_REVIEWER,justification="governed rejection")
    assert rejected.review_status is HumanReviewStatus.REJECTED_BY_REVIEWER and not rejected.recommendations[0].externally_actionable
