from dataclasses import FrozenInstanceError,replace
import pytest
from jmoraIs.reasoning_input.exact_reference import *
from tests.test_reasoning_input_exact_upstream_lineage import state_reference,evidence_reference,NOW
from jmoraIs.terminology.domain import MappingType,PersistedTerminologyMappingGovernanceReference

def reference():
    term=PersistedTerminologyMappingGovernanceReference("tmr_"+"b"*32,"record",1,"concept","terms","source",MappingType.EXACT,"SHARED_GLOBAL_REFERENCE","policy","6"*64,NOW)
    value=PersistedClinicalReasoningInputReference("rir_"+"a"*32,"input",1,None,None,"subject","tenant","policy","prov","1"*64,state_reference(),(evidence_reference(),),(term,),"0"*64,NOW)
    return replace(value,integrity_hash=reference_integrity(value))

def test_reference_is_immutable_metadata_only_and_tamper_evident():
    value=reference();assert validate_reference_integrity(value)
    assert not {"payload","clinical_state","governed_evidence"}.intersection(value.__dict__)
    with pytest.raises(FrozenInstanceError):value.input_version=2
    assert not validate_reference_integrity(replace(value,policy_version="wrong"))

def test_invalid_versions_and_missing_upstream_fail_closed():
    with pytest.raises(ClinicalReasoningInputReferenceRejected):replace(reference(),input_version=0)
    with pytest.raises(ClinicalReasoningInputReferenceRejected):replace(reference(),governed_evidence_references=())
