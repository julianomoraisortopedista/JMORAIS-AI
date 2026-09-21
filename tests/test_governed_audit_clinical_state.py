from dataclasses import replace

import pytest

from jmoraIs.audit_defense import (
    AuditClinicalStateProjectionService,
    AuditDefenseBoundaryRejected,
    GovernedAuditClinicalFact,
)
from jmoraIs.clinical_state.domain import (
    DataQualityFlag,
    DataQualityFlagType,
    EpistemicStatus,
    StatementReference,
)
from tests.test_governed_document_clinical_state import rich_state
from tests.test_governed_orthopedic_state import NOW


def governed_state():
    base = rich_state()
    procedure = StatementReference("procedure-1", "arthroscopy", "concept-procedure", EpistemicStatus.CONFIRMED,
                                   "history", "event-procedure", NOW, "prov:procedure")
    implant = StatementReference("implant-1", "screw", "concept-implant", EpistemicStatus.REPORTED,
                                 "history", "event-implant", NOW, "prov:implant")
    flags = base.quality_flags + (
        DataQualityFlag(DataQualityFlagType.STALE_DATA, ("symptom-1",), "stale"),
        DataQualityFlag(DataQualityFlagType.MISSING_DATA, ("laboratory",), "missing"),
    )
    return replace(base, procedures=(procedure,), implants=(implant,), quality_flags=flags)


def test_projection_is_deterministic_reference_only_and_governed():
    service = AuditClinicalStateProjectionService(); state = governed_state()
    first = service.project(state)
    assert first == service.project(state) and all(isinstance(item, GovernedAuditClinicalFact) for item in first)
    indexed = {item.fact_id: item for item in first}
    assert indexed["symptom-1"].epistemic_status == "SUSPECTED"
    assert indexed["finding-1"].epistemic_status == "INFERRED"
    assert indexed["procedure-1"].fact_type == "PROCEDURE_HISTORY"
    assert indexed["implant-1"].fact_type == "IMPLANT"
    assert {"MISSING_DATA", "CONFLICTING_DATA", "STALE_DATA"} <= set(indexed["symptom-1"].quality_flags)
    assert indexed["symptom-1"].review_status == "REVIEW_REQUIRED"
    assert indexed["symptom-1"].pseudonymous_subject_reference == state.pseudonymous_patient_id
    assert indexed["symptom-1"].policy_version == service.POLICY
    assert "prov:state" in indexed["symptom-1"].provenance_references
    assert any(item.fact_type == "FUNCTIONAL_LIMITATION" for item in first) is False
    assert any(item.fact_type == "ORTHOPEDIC_REFERENCE" for item in first)
    assert sum(item.fact_type == "DATA_QUALITY_REFERENCE" for item in first) == len(state.quality_flags)


def test_historical_versions_remain_distinct_and_reconstructible():
    service = AuditClinicalStateProjectionService(); first_state = governed_state()
    second_state = replace(first_state, state_id="state-2", state_version=2, previous_state_id=first_state.state_id)
    first = service.project(first_state); second = service.project(second_state)
    assert all(item.clinical_state_version == 1 for item in first)
    assert all(item.clinical_state_version == 2 for item in second)
    assert first != second and first == service.project(first_state)


def test_projection_rejects_noncanonical_state():
    with pytest.raises(AuditDefenseBoundaryRejected):
        AuditClinicalStateProjectionService().project({"state_id": "forged"})
