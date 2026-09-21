from dataclasses import FrozenInstanceError,replace
from datetime import datetime,timezone
import pytest
from jmoraIs.medical_documents.exact_reference import *

NOW=datetime(2026,9,6,tzinfo=timezone.utc)
def reference(**changes):
    value=PersistedMedicalDocumentVersionReference("mdr_"+"a"*32,"stream-1","document-1","version-1",1,None,
        "tenant-1","MIP-08","CLINICAL_REPORT","TRUE","REVIEW_REQUIRED","b"*64,"medical-document-provenance:"+"c"*64,
        "reasoning-1",1,"state-1",1,None,None,"d"*64,"0"*64,NOW)
    value=replace(value,integrity_hash=medical_document_reference_integrity(value))
    if changes:
        value=replace(value,**changes,integrity_hash="0"*64);value=replace(value,integrity_hash=medical_document_reference_integrity(value))
    return value
def test_reference_is_immutable_metadata_only_and_hash_protected():
    value=reference();assert validate_medical_document_reference(value)
    assert not {"sections","content","document","clinical_payload"}.intersection(value.__dict__)
    with pytest.raises(FrozenInstanceError):value.version=2
    assert not validate_medical_document_reference(replace(value,document_id="tampered"))
def test_reference_rejects_invalid_versions_and_hashes():
    with pytest.raises(MedicalDocumentReferenceRejected):reference(version=0)
    with pytest.raises(MedicalDocumentReferenceRejected):reference(document_integrity_hash="short")
