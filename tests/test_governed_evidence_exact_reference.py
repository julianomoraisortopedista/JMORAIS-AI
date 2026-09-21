from dataclasses import FrozenInstanceError,replace
import pytest
from jmoraIs.appraisal.exact_reference import *
from tests.test_evidence_package_boundary import NOW

def reference(**changes):
    value=PersistedGovernedEvidenceReference("ger_"+"a"*32,"evidence-1",1,"tenant-a","package-1","appraisal-1",1,"ST-13.1","lifecycle-1","ACTIVE","b"*64,"governed-evidence-provenance:"+"c"*64,"d"*64,"0"*64,NOW)
    value=replace(value,integrity_hash=reference_integrity(value))
    if changes:
        value=replace(value,**changes,integrity_hash="0"*64);value=replace(value,integrity_hash=reference_integrity(value))
    return value

def test_reference_is_immutable_metadata_only_and_integrity_protected():
    value=reference();assert validate_reference_integrity(value)
    assert not {"payload","scientific_payload","article","appraisal_payload"}.intersection(value.__dict__)
    with pytest.raises(FrozenInstanceError):value.stream_version=2
    assert not validate_reference_integrity(replace(value,policy_version="tampered"))

def test_reference_rejects_invalid_lifecycle_versions_and_hashes():
    with pytest.raises(GovernedEvidenceReferenceRejected):replace(reference(),lifecycle_status="INVALIDATED")
    with pytest.raises(GovernedEvidenceReferenceRejected):replace(reference(),stream_version=0)
    with pytest.raises(GovernedEvidenceReferenceRejected):replace(reference(),lifecycle_integrity_hash="short")
