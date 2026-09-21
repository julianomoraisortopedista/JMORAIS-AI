from dataclasses import FrozenInstanceError, replace
from datetime import timedelta

import pytest

from jmoraIs.patient_context.exact_reference import (
    PatientContextReferenceRejected, PersistedPatientContextReference,
    reference_integrity, validate_reference_integrity,
)
from tests.test_patient_context_domain import NOW, PATIENT_ID


def reference(**changes):
    value = PersistedPatientContextReference("pcr_" + "a" * 32, "context-1", 1,
        PATIENT_ID, "tenant-a", "privacy-v1", "ingestion-1", "b" * 64,
        "0" * 64, NOW)
    value = replace(value, integrity_hash=reference_integrity(value))
    if changes:
        value = replace(value, **changes, integrity_hash="0" * 64)
        value = replace(value, integrity_hash=reference_integrity(value))
    return value


def test_reference_is_immutable_metadata_only_and_integrity_protected():
    value = reference()
    assert validate_reference_integrity(value)
    assert not any(name in value.__dict__ for name in
        ("payload", "clinical_text", "name", "email", "phone", "national_identifier"))
    with pytest.raises(FrozenInstanceError): value.version = 2
    assert not validate_reference_integrity(replace(value, issued_at=NOW + timedelta(seconds=1)))


def test_reference_rejects_incomplete_or_invalid_metadata():
    with pytest.raises(PatientContextReferenceRejected):
        replace(reference(), policy_version="")
    with pytest.raises(PatientContextReferenceRejected):
        replace(reference(), context_integrity_hash="short")
