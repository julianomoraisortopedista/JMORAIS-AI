from dataclasses import replace
from pathlib import Path
from uuid import uuid4
import pytest
from jmoraIs.reasoning_input import ClinicalReasoningInputService,InvalidReasoningInput,ReasoningTerminologyLineageStatus
from jmoraIs.terminology import (CodeSystem,InMemoryTerminologyMappingGovernanceRepository,MappingConfidence,MappingOutcome,
    MappingReviewStatus,MappingType,MappedClinicalConcept,PersistedTerminologyMappingGovernanceReference,
    TerminologyMappingGovernanceService)
from tests.test_reasoning_input import NOW,draft,setup
from tests.test_terminology import concept

def _governed(repository,*,review_status=MappingReviewStatus.AUTO_MAPPED,review_required=False,mapping_type=MappingType.EXACT):
    item=replace(concept("concept-reasoning"),version="terms-2026.1")
    mapped=MappedClinicalConcept(item.preferred_term,CodeSystem.ORTHOPEDIC,item.version,MappingOutcome.MAPPED,(item,),item.canonical_id,MappingConfidence.HIGH,review_required,("prov:terminology",))
    return TerminologyMappingGovernanceService(repository,clock=lambda:NOW).persist(mapped,source_reference="state:fact-1",target_concept_id=item.canonical_id,mapping_type=mapping_type,review_status=review_status,review_required=review_required,mapping_method="deterministic",policy_version="terminology-mapping-v1")

def test_exact_multiple_references_are_owner_issued_sorted_and_preserved():
    governance=InMemoryTerminologyMappingGovernanceRepository();first=_governed(governance)
    second=replace(first,governance_record_id="tmg_"+uuid4().hex,source_reference="state:fact-2",target_concept_id="concept-reasoning-2",predecessor_record_id=None,integrity_hash="pending")
    item=replace(concept("concept-reasoning-2"),version="terms-2026.1")
    mapped=MappedClinicalConcept(item.preferred_term,CodeSystem.ORTHOPEDIC,item.version,MappingOutcome.MAPPED,(item,),item.canonical_id,MappingConfidence.HIGH,False,("prov:terminology-2",))
    second=TerminologyMappingGovernanceService(governance,clock=lambda:NOW).persist(mapped,source_reference="state:fact-2",target_concept_id=item.canonical_id,mapping_type=MappingType.EXACT,review_status=MappingReviewStatus.AUTO_MAPPED,review_required=False,mapping_method="deterministic",policy_version="terminology-mapping-v1")
    references=(governance.reference_for(second),governance.reference_for(first));repository=setup()[1];audit=setup()[2]
    service=ClinicalReasoningInputService(repository,audit,clock=lambda:NOW,terminology_governance=governance)
    value=service.build(replace(draft(),terminology_governance_references=references),actor_id="system",source_reference="assembly")
    assert value.terminology_governance_references==tuple(sorted(references,key=lambda item:item.reference_id))
    assert value.terminology_lineage_status is ReasoningTerminologyLineageStatus.EXACT

def test_forged_duplicate_mismatched_and_review_required_references_fail_closed():
    governance=InMemoryTerminologyMappingGovernanceRepository();record=_governed(governance);reference=governance.reference_for(record)
    repository=setup()[1];audit=setup()[2];service=ClinicalReasoningInputService(repository,audit,clock=lambda:NOW,terminology_governance=governance)
    for references,version in (((reference,reference),"terms-2026.1"),((replace(reference,integrity_hash="0"*64),),"terms-2026.1"),((reference,),"wrong-version"),((PersistedTerminologyMappingGovernanceReference("tmr_"+uuid4().hex,reference.governance_record_id,reference.record_version,reference.target_concept_id,reference.terminology_version,reference.source_reference,reference.mapping_type,reference.classification,reference.policy_version,reference.integrity_hash,reference.issued_at),),"terms-2026.1")):
        with pytest.raises(InvalidReasoningInput):service.build(replace(draft(),terminology_version=version,terminology_governance_references=references),actor_id="system",source_reference="assembly")
    governed_review=InMemoryTerminologyMappingGovernanceRepository();review_record=_governed(governed_review,review_status=MappingReviewStatus.REVIEW_REQUIRED,review_required=True)
    review_service=ClinicalReasoningInputService(setup()[1],setup()[2],clock=lambda:NOW,terminology_governance=governed_review)
    with pytest.raises(InvalidReasoningInput):review_service.build(replace(draft(),terminology_governance_references=(governed_review.reference_for(review_record),)),actor_id="system",source_reference="assembly")

def test_legacy_input_is_explicit_and_architecture_isolated():
    value=setup()[0].build(draft(),actor_id="system",source_reference="assembly")
    assert value.terminology_lineage_status is ReasoningTerminologyLineageStatus.LEGACY_MISSING_EXACT_TERMINOLOGY_GOVERNANCE_REFERENCE
    root=Path(__file__).parents[1];application=(root/"jmoraIs/reasoning_input/application.py").read_text();production="\n".join(path.read_text() for path in (root/"jmoraIs").rglob("*.py"))
    assert "get_exact(reference)" in application and "latest" not in application.split("def _validate_terminology",1)[1].split("def validate",1)[0]
    assert "evaluation.e2e_acceptance" not in production
