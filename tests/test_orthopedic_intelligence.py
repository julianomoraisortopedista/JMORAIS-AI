from dataclasses import FrozenInstanceError,replace
from datetime import datetime,timezone
import pytest
from jmoraIs.orthopedic_intelligence import *
from jmoraIs.clinical import *
from jmoraIs.guideline_engine import InMemoryRecommendationRepository
from tests.test_guideline_engine import ready_input,setup as guideline_setup,evidence,Lifecycle
from tests.test_terminology import concept

NOW=datetime(2026,8,10,tzinfo=timezone.utc)
class Query:
    def __init__(self,items,key):self.items={getattr(x,key):x for x in items}
    def get(self,key):return self.items.get(key)
class Guidelines:
    def __init__(self,value):self.value=value
    def latest(self,subject):return self.value
def finding(identifier="finding-1",joint=AnatomicalScope.KNEE,side=OrthopedicLaterality.RIGHT,category=FindingCategory.PAIN,epistemic="OBSERVED",severity=Severity.UNKNOWN,scale=None):
    return OrthopedicFindingReference(identifier,"concept-1",joint,side,category,"clinical-state",.9,"prov:finding",epistemic,severity,scale)
def view(*findings,stability=(),imaging=(),functional=(),surgeries=(),implants=(),flags=()):
    inp=ready_input();return GovernedOrthopedicStateView(inp.patient_clinical_state.reference_id,inp.patient_clinical_state.clinical_state_version,inp.terminology_version,tuple(findings),tuple(stability),tuple(imaging),tuple(functional),tuple(surgeries),tuple(implants),tuple(flags),("prov:state",))
def engine(state,evidences=None,guidelines=None,concepts=None):
    inp=ready_input();c=replace(concept(),canonical_id="concept-1",version=inp.terminology_version)
    gengine,grepo,_=guideline_setup(evidences=evidences or (evidence(),),concepts=(c,));gset=guidelines or gengine.create_recommendation_set(inp,(c.canonical_id,))
    repo=InMemoryOrthopedicAssessmentRepository();audit=InMemoryOrthopedicAuditAdapter();canonical=InMemoryGovernedDecisionAuditRepository();auth=InMemoryReviewerAuthorizationAdapter((ReviewerIdentity("reviewer",ReviewerRole.SENIOR_REVIEWER),));review=AuthorizedRecommendationReviewService(auth,canonical,ReviewAuthorizationPolicy(),clock=lambda:NOW)
    return OrthopedicIntelligenceService(InMemoryGovernedOrthopedicStateQueryAdapter((state,)),Query(evidences or (evidence(),),"governed_evidence_id"),Lifecycle(),Guidelines(gset),Query(concepts or (c,),"canonical_id"),repo,audit,review,clock=lambda:NOW),repo,audit,inp

@pytest.mark.parametrize("joint",[AnatomicalScope.KNEE,AnatomicalScope.HIP,AnatomicalScope.ANKLE,AnatomicalScope.SHOULDER])
def test_supported_joint_assessment_is_reference_only_immutable_and_explainable(joint):
    service,_,audit,inp=engine(view(finding(joint=joint)));result=service.generate(inp);item=result.assessment
    assert item.joints[0].joint is joint and item.readiness is AssessmentReadiness.READY_FOR_HUMAN_REVIEW
    assert item.joints[0].problems[0].finding_references==("finding-1",) and item.governed_evidence_ids==("governed-1",)
    assert not item.externally_actionable and audit.history(inp.subject_reference)
    with pytest.raises(FrozenInstanceError):item.readiness=AssessmentReadiness.BLOCKED

def test_mechanical_stability_alignment_function_and_history_are_structured_references():
    f=(finding(category=FindingCategory.LOCKING),finding("finding-2",category=FindingCategory.INSTABILITY),finding("finding-3",category=FindingCategory.ALIGNMENT_ABNORMALITY))
    stable=StabilityFindingReference("lachman-1","concept-1",AnatomicalScope.KNEE,OrthopedicLaterality.RIGHT,"positive","exam",.8,"prov:exam","OBSERVED")
    functional=FunctionalReference("function-1","antalgic",("ADL-1",),("WORK-1",),("SPORT-1",),"limited","500m","partial","score:koos","prov:function")
    surgery=SurgicalHistoryReference("surgery-1","concept-1",AnatomicalScope.KNEE,OrthopedicLaterality.RIGHT,NOW,None,None,"prov:surgery")
    implant=ImplantStateReference("implant-1","concept-1",AnatomicalScope.KNEE,OrthopedicLaterality.RIGHT,NOW,"primary","prov:implant")
    service,_,_,inp=engine(view(*f,stability=(stable,),functional=(functional,),surgeries=(surgery,),implants=(implant,)))
    joint=service.generate(inp).assessment.joints[0]
    assert joint.mechanical.mechanical_symptom_references==("finding-1",) and joint.stability.examination_references==("lachman-1",)
    assert joint.alignment.finding_references==("finding-3",) and joint.functional.validated_score_references==("score:koos",)
    assert joint.surgery_references==("surgery-1",) and joint.implant_references==("implant-1",)

def test_epistemic_status_not_promoted_and_unsupported_severity_fails_closed():
    state=view(finding(epistemic="SUSPECTED",severity=Severity.SEVERE))
    result=engine(state)[0].generate(ready_input()).assessment
    assert result.joints[0].problems[0].status is OrthopedicProblemStatus.SUSPECTED
    assert result.joints[0].problems[0].severity is Severity.UNKNOWN and result.readiness is AssessmentReadiness.REVIEW_REQUIRED

def test_imaging_concordance_discordance_and_insufficient_data():
    matching=ImagingFindingReference("img-1","concept-1","MRI",AnatomicalScope.KNEE,OrthopedicLaterality.RIGHT,"radiology","prov:img")
    other=replace(matching,reference_id="img-2",finding_concept_id="concept-2")
    c2=replace(concept(),canonical_id="concept-2",version=ready_input().terminology_version)
    state=view(finding(),imaging=(matching,other));service,_,_,inp=engine(state,concepts=(replace(concept(),canonical_id="concept-1",version=ready_input().terminology_version),c2))
    statuses={x.status for x in service.generate(inp).assessment.joints[0].imaging}
    assert statuses=={ConcordanceStatus.CONCORDANT,ConcordanceStatus.DISCORDANT}
    no_clinical=view(imaging=(matching,));service,_,_,inp=engine(no_clinical)
    assert service.generate(inp).assessment.joints[0].imaging[0].status is ConcordanceStatus.INSUFFICIENT_DATA

def test_evidence_directions_and_guideline_correlation_are_preserved():
    ev=evidence(directions=("SUPPORTING","OPPOSING","NEUTRAL","INCONCLUSIVE"));service,_,_,inp=engine(view(finding()),(ev,));problem=service.generate(inp).assessment.joints[0].problems[0]
    assert problem.evidence.supporting==problem.evidence.opposing==problem.evidence.neutral==problem.evidence.inconclusive==("governed-1",)
    assert problem.guidelines[0].status is GuidelineCorrelationStatus.APPLICABLE

def test_laterality_conflict_and_missing_findings_are_not_silently_resolved():
    service,_,_,inp=engine(view(finding(),finding("left",side=OrthopedicLaterality.LEFT)))
    assert service.generate(inp).assessment.readiness is AssessmentReadiness.CONFLICTING_DATA
    service,_,_,inp=engine(view())
    assert service.generate(inp).assessment.readiness is AssessmentReadiness.INSUFFICIENT_DATA

@pytest.mark.parametrize("invalid",[{},object(),"raw PatientContext","raw EvidencePackage"])
def test_boundary_rejects_noncanonical_inputs(invalid):
    service,_,_,_=engine(view(finding()))
    with pytest.raises(OrthopedicBoundaryError):service.generate(invalid)

def test_invalid_terminology_and_raw_governance_objects_are_rejected():
    service,_,_,inp=engine(view(finding()),concepts=())
    service._terminology=Query((),"canonical_id")
    with pytest.raises(OrthopedicBoundaryError):service.generate(inp)
    bad=replace(inp,readiness=inp.readiness.REVIEW_REQUIRED)
    with pytest.raises(OrthopedicBoundaryError):engine(view(finding()))[0].generate(bad)

def test_inactive_governed_evidence_is_rejected():
    service,_,_,inp=engine(view(finding()));service._evidence_lifecycle=Lifecycle("RETRACTED")
    with pytest.raises(OrthopedicBoundaryError):service.generate(inp)

def test_review_uses_canonical_governance_and_external_use_remains_disabled():
    service,repo,_,inp=engine(view(finding()));pending=service.generate(inp)
    approved=service.submit_for_human_review(inp.subject_reference,reviewer_id="reviewer",target=HumanReviewStatus.APPROVED_BY_REVIEWER,justification="specialist reviewed")
    assert approved.review_status is HumanReviewStatus.APPROVED_BY_REVIEWER and not approved.assessment.externally_actionable
    assert service.reconstruct(inp.subject_reference,1)==pending and len(repo.history(inp.subject_reference))==2

def test_repository_is_append_only_and_chain_validated():
    service,repo,_,inp=engine(view(finding()));first=service.generate(inp)
    with pytest.raises(OrthopedicVersionConflict):repo.append(first)
    with pytest.raises(OrthopedicVersionConflict):repo.append(replace(first,set_id="forged",set_version=3,previous_set_id="wrong"))
