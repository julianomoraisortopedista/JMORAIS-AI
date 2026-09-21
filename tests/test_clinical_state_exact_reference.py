from dataclasses import FrozenInstanceError, replace

import pytest

from jmoraIs.clinical_state.exact_reference import (
    ClinicalStateReferenceRejected, ClinicalStateTimelineReferenceRejected,
    PersistedClinicalStateReference, PersistedClinicalStateTimelineReference,
    reference_integrity, timeline_integrity, validate_reference_integrity,
    validate_timeline_integrity,
)
from tests.test_patient_context_domain import NOW, PATIENT_ID


def state_reference(version=1, predecessor=None):
    unsigned = PersistedClinicalStateReference("csr_" + str(version) * 32,
        "state-" + str(version), version, PATIENT_ID, "tenant-a", "privacy-v1",
        predecessor.reference_id if predecessor else None, version - 1 if predecessor else None,
        "clinical-state-provenance:" + "a" * 64, "b" * 64, "0" * 64, NOW)
    return replace(unsigned, integrity_hash=reference_integrity(unsigned))


def timeline(references):
    unsigned = PersistedClinicalStateTimelineReference("cst_" + "a" * 32,
        PATIENT_ID, "tenant-a", "privacy-v1", tuple(references), "0" * 64, NOW)
    return replace(unsigned, integrity_hash=timeline_integrity(unsigned))


def test_exact_reference_and_timeline_are_immutable_metadata_only_and_hash_protected():
    first = state_reference(); second = state_reference(2, first); value = timeline((first, second))
    assert validate_reference_integrity(first) and validate_timeline_integrity(value)
    assert not {"payload", "clinical_text", "fhir_payload", "document"}.intersection(first.__dict__)
    with pytest.raises(FrozenInstanceError): first.state_version = 2
    assert not validate_reference_integrity(replace(first, state_id="tampered"))
    assert not validate_timeline_integrity(replace(value, state_references=(second, first)))


def test_reference_models_reject_invalid_versions_predecessors_and_hashes():
    first = state_reference()
    with pytest.raises(ClinicalStateReferenceRejected): replace(first, state_integrity_hash="short")
    with pytest.raises(ClinicalStateReferenceRejected): replace(first, predecessor_reference_id="unexpected")
    with pytest.raises(ClinicalStateReferenceRejected): replace(first, state_version=2)
    with pytest.raises(ClinicalStateTimelineReferenceRejected):
        PersistedClinicalStateTimelineReference("cst_x", PATIENT_ID, "tenant-a", "privacy-v1", (), "a" * 64, NOW)
