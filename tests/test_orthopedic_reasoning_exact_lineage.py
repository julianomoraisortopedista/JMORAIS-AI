from dataclasses import replace
import pytest
from jmoraIs.orthopedic_intelligence import OrthopedicBoundaryError
from tests.test_orthopedic_intelligence import engine,finding,view
from tests.test_reasoning_input_exact_reference import reference as reasoning_reference

class Exact:
    def __init__(self,value,reference):self.value=value;self.reference=reference
    def get_exact(self,reference):
        if reference!=self.reference:raise RuntimeError
        return self.value

def test_generation_preserves_owner_issued_exact_reasoning_reference():
    service,_,_,value=engine(view(finding()))
    reference=replace(reasoning_reference(),input_id=value.input_id,input_version=value.input_version,
        previous_input_id="previous" if value.input_version>1 else None,
        predecessor_reference_id="rir_previous" if value.input_version>1 else None,
        subject_reference=value.subject_reference)
    service._reasoning_inputs=Exact(value,reference)
    result=service.generate(value,reasoning_input_reference=reference)
    assert result.clinical_reasoning_input_reference==reference
    assert result.reasoning_lineage_status=="EXACT"

def test_missing_or_forged_reference_fails_closed_and_legacy_is_explicit():
    service,_,_,value=engine(view(finding()));reference=reasoning_reference()
    with pytest.raises(OrthopedicBoundaryError):service.generate(value,reasoning_input_reference=reference)
    assert engine(view(finding()))[0].generate(value).reasoning_lineage_status=="LEGACY_MISSING_CLINICAL_REASONING_INPUT_REFERENCE"
