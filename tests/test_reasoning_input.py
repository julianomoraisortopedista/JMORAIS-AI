from dataclasses import FrozenInstanceError,fields,replace
from datetime import date,datetime,timezone
import pytest
from jmoraIs.reasoning_input import *

NOW=datetime(2026,8,10,tzinfo=timezone.utc);SUBJECT="pt_"+("b"*64)
TRACE=dict(origin="governed-boundary",author="system",recorded_at=NOW,policy_version="MIP-04-v1")
def package(identifier="package-1"):return EvidencePackageReference(identifier,**TRACE)
def evidence(identifier="governed-1",package_id="package-1",direction=EvidenceDirection.SUPPORTING):return GovernedEvidenceReference(identifier,**TRACE,evidence_package_reference_id=package_id,direction=direction)
def guideline(identifier="guideline-1"):return GuidelineReference(identifier,**TRACE,guideline_version="2026.1",organization="Society",publication_date=date(2026,1,1),strength="CONDITIONAL",status="ACTIVE",applicability=("ADULT",))
def quality(**changes):
    values=dict(missing_data_references=(),conflicting_data_references=(),stale_data_references=(),review_required=False,mapping_confidence=.95,terminology_confidence=.95,overall_input_completeness=.95);values.update(changes);return DataQualitySummary(**values)
def draft(**changes):
    state=PatientClinicalStateReference("cs-1",**TRACE,patient_context_version=3,clinical_state_version=4)
    value=dict(subject_reference=SUBJECT,patient_clinical_state=state,terminology_version="terms-2026.1",
      evidence=EvidenceReferenceSummary(supporting=(evidence(),)),evidence_packages=(package(),),applicable_guidelines=(guideline(),),
      timeline=TimelineReference("timeline-1",**TRACE),quality=quality(),provenance_references=(TraceableReference("prov-1",**TRACE),),
      audit_references=(AuditReference("audit-1",**TRACE),),policy_versions=(PolicyVersionReference("policy-ref-1",**TRACE,policy_name="clinical-input"),))
    value.update(changes);return ClinicalReasoningInputDraft(**value)
def setup():
    repository=InMemoryClinicalReasoningInputRepository();audit=InMemoryReasoningInputAuditAdapter()
    return ClinicalReasoningInputService(repository,audit,clock=lambda:NOW),repository,audit

def test_contract_is_immutable_reference_only_and_contains_versions():
    service,_,_=setup();value=service.build(draft(),actor_id="system",source_reference="assembly")
    assert value.patient_clinical_state.patient_context_version==3 and value.patient_clinical_state.clinical_state_version==4
    assert value.terminology_version=="terms-2026.1" and value.timeline.reference_id=="timeline-1"
    with pytest.raises(FrozenInstanceError):value.readiness=ReasoningReadiness.BLOCKED
    names={item.name for item in fields(ClinicalReasoningInput)}
    assert not ({"patient_context","clinical_state","laboratory","images","timeline_events","evidence_package"}&names)

def test_evidence_summary_preserves_all_directions_without_payload_duplication():
    summary=EvidenceReferenceSummary((evidence("s"),),(evidence("o",direction=EvidenceDirection.OPPOSING),),(evidence("n",direction=EvidenceDirection.NEUTRAL),),(evidence("i",direction=EvidenceDirection.INCONCLUSIVE),))
    value=setup()[0].build(draft(evidence=summary),actor_id="system",source_reference="assembly")
    assert tuple(item.direction for item in value.evidence.all)==tuple(EvidenceDirection)
    with pytest.raises(InvalidReasoningInput):EvidenceReferenceSummary(supporting=(evidence("duplicate"),),opposing=(evidence("duplicate",direction=EvidenceDirection.OPPOSING),))
    with pytest.raises(InvalidReasoningInput):setup()[0].build(draft(evidence_packages=()),actor_id="system",source_reference="assembly")

@pytest.mark.parametrize("summary,expected",[
  (quality(missing_data_references=("missing",)),ReasoningReadiness.INSUFFICIENT_DATA),
  (quality(conflicting_data_references=("conflict",)),ReasoningReadiness.CONFLICTING_INPUT),
  (quality(review_required=True),ReasoningReadiness.REVIEW_REQUIRED),
  (quality(overall_input_completeness=.5),ReasoningReadiness.INSUFFICIENT_DATA)])
def test_quality_summary_calculates_fail_closed_readiness(summary,expected):
    value=setup()[0].build(draft(quality=summary),actor_id="system",source_reference="assembly")
    assert value.readiness is expected

def test_auto_assembled_requires_review_then_can_be_approved_or_rejected():
    service,repository,audit=setup();initial=service.build(draft(),actor_id="system",source_reference="assembly")
    assert initial.readiness is ReasoningReadiness.REVIEW_REQUIRED
    reviewed=service.mark_reviewed(SUBJECT,actor_id="physician",source_reference="review:1")
    assert reviewed.review_status is ReasoningReviewStatus.REVIEWED and reviewed.readiness is ReasoningReadiness.READY_FOR_REASONING
    approved=service.approve(SUBJECT,actor_id="physician",source_reference="approval:1")
    assert approved.review_status is ReasoningReviewStatus.APPROVED
    rejected=service.reject(SUBJECT,actor_id="physician",source_reference="rejection:1")
    assert rejected.readiness is ReasoningReadiness.BLOCKED
    assert tuple(item.input_version for item in repository.history(SUBJECT))==(1,2,3,4)
    assert {item.event_type for item in audit.history(SUBJECT)}>={ReasoningAuditType.CREATION,ReasoningAuditType.APPROVAL,ReasoningAuditType.REJECTION}

def test_validation_and_reconstruction_are_deterministic_and_audited():
    service,repository,audit=setup();value=service.build(draft(),actor_id="system",source_reference="assembly")
    validation=service.validate(value.input_id,actor_id="validator",source_reference="validation:1")
    reconstructed=service.reconstruct(SUBJECT,1)
    assert validation.valid and reconstructed==value
    assert [item.event_type for item in audit.history(SUBJECT)][-2:]==[ReasoningAuditType.VALIDATION,ReasoningAuditType.RECONSTRUCTION]
    query=ClinicalReasoningInputQueryService(repository)
    assert query.get(value.input_id)==value and query.latest(SUBJECT)==value and query.reconstruct(SUBJECT,1)==value

def test_traceability_and_guideline_governance_are_mandatory():
    with pytest.raises(InvalidReasoningInput):guideline("")
    with pytest.raises(InvalidReasoningInput):DataQualitySummary((),(),(),False,1.1,1,1)
    with pytest.raises(InvalidReasoningInput):setup()[0].build(draft(provenance_references=()),actor_id="system",source_reference="assembly")
