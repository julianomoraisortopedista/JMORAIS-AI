from dataclasses import replace
from types import SimpleNamespace
import pytest

from jmoraIs.appraisal.exact_reference import PersistedGovernedEvidenceReference
from jmoraIs.clinical_state.exact_reference import PersistedClinicalStateReference
from jmoraIs.reasoning_input import (
    ClinicalReasoningInputService, InvalidReasoningInput,
    ReasoningUpstreamLineageStatus,
)
from jmoraIs.reasoning_input.persistence import ReasoningInputJsonCodec
from test_reasoning_input import NOW, SUBJECT, draft, setup


class ExactPort:
    def __init__(self, values): self.values = values
    def get_exact(self, reference):
        try: return self.values[reference]
        except (KeyError, TypeError) as exc: raise RuntimeError("unknown exact reference") from exc


def state_reference():
    return PersistedClinicalStateReference("csr_"+"a"*32,"cs-1",4,SUBJECT,"tenant-1","policy-v1", "csr_prior",3,"prov:state","1"*64,"2"*64,NOW)


def evidence_reference(identifier="governed-1"):
    return PersistedGovernedEvidenceReference("ger_"+identifier,identifier,1,"tenant-1","package-1","appraisal-1",1,"policy-v1","event-1","ACTIVE","3"*64,"prov:evidence","4"*64,"5"*64,NOW)


def test_exact_owner_references_are_validated_sorted_and_persisted():
    state_ref=state_reference();evidence_ref=evidence_reference()
    state=SimpleNamespace(state_id="cs-1",state_version=4,patient_context_version=3)
    governed=SimpleNamespace(governed_evidence_id="governed-1",evidence_package_id="package-1")
    service,repository,_=setup()
    service=ClinicalReasoningInputService(repository,service._audit,clock=lambda:NOW,
        clinical_states=ExactPort({state_ref:state}),governed_evidence=ExactPort({evidence_ref:governed}))
    # A terminology reference is required for a complete exact lineage; use the
    # established fixture-shaped immutable reference and an exact owner port.
    from jmoraIs.terminology.domain import MappingReviewStatus, MappingType, PersistedTerminologyMappingGovernanceReference
    term=PersistedTerminologyMappingGovernanceReference("tmr_"+"b"*32,"record-1",1,"concept-1","terms-2026.1","source-1",MappingType.EXACT,"SHARED_GLOBAL_REFERENCE","policy-v1","6"*64,NOW)
    term_record=SimpleNamespace(terminology_version="terms-2026.1",review_required=False,review_status=MappingReviewStatus.AUTO_MAPPED,mapping_type=MappingType.EXACT)
    service._terminology_governance=ExactPort({term:term_record})
    value=service.build(replace(draft(),clinical_state_reference=state_ref,
        governed_evidence_references=(evidence_ref,),terminology_governance_references=(term,)),actor_id="system",source_reference="assembly")
    assert value.clinical_state_reference==state_ref
    assert value.governed_evidence_references==(evidence_ref,)
    assert value.exact_upstream_lineage_status is ReasoningUpstreamLineageStatus.EXACT
    assert ReasoningInputJsonCodec().decode(ReasoningInputJsonCodec().encode(value))==value


def test_partial_fabricated_duplicate_and_scalar_only_lineage_fail_closed():
    state_ref=state_reference();evidence_ref=evidence_reference()
    service=setup()[0]
    with pytest.raises(InvalidReasoningInput): service.build(replace(draft(),clinical_state_reference=state_ref),actor_id="system",source_reference="assembly")
    with pytest.raises(InvalidReasoningInput): service.build(replace(draft(),governed_evidence_references=(evidence_ref,evidence_ref)),actor_id="system",source_reference="assembly")
    legacy=setup()[0].build(draft(),actor_id="system",source_reference="legacy")
    assert legacy.exact_upstream_lineage_status is ReasoningUpstreamLineageStatus.LEGACY_MISSING_PERSISTED_CLINICAL_REASONING_INPUT_REFERENCE
