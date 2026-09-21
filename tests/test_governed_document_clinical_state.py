from dataclasses import replace
from jmoraIs.clinical_state.domain import EpistemicStatus,StatementReference
from jmoraIs.medical_documents import *
from tests.test_governed_orthopedic_state import NOW,state

def rich_state():
    suspected=StatementReference("symptom-1","reported locking","locking",EpistemicStatus.SUSPECTED,"history","event-1",NOW,"prov:symptom")
    inferred=StatementReference("finding-1","possible stiffness","stiffness",EpistemicStatus.INFERRED,"projection-source","event-2",NOW,"prov:finding")
    return replace(state(),symptoms=(suspected,),findings=(inferred,))
def test_projection_preserves_epistemic_status_quality_provenance_and_version():
    service=DocumentClinicalStateProjectionService();value=rich_state();first=service.project(value);second=service.project(value)
    assert first==second and all(isinstance(x,DocumentFactReference) for x in first)
    indexed={x.fact_id:x for x in first}
    assert indexed["symptom-1"].epistemic_status is FactEpistemicStatus.FACT_SUSPECTED
    assert indexed["finding-1"].epistemic_status is FactEpistemicStatus.FACT_INFERRED
    assert indexed["symptom-1"].source_reference_id==value.state_id and indexed["symptom-1"].source_version=="1"
    assert "CONFLICTING_DATA" in indexed["symptom-1"].data_quality_flags
    assert indexed["symptom-1"].review_status=="REVIEW_REQUIRED" and "prov:state" in indexed["symptom-1"].provenance_references
    assert any(x.statement.startswith("orthopedic reference:") for x in first)
def test_projection_rejects_noncanonical_state():
    import pytest
    with pytest.raises(DocumentBoundaryRejected):DocumentClinicalStateProjectionService().project({"state_id":"forged"})
