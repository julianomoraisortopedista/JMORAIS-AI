from dataclasses import FrozenInstanceError, replace

import pytest

from jmoraIs.patient_context.infrastructure import PatientContextPersistenceError
from jmoraIs.patient_context.privacy import sign_authorized_ingestion_record,validate_authorized_ingestion_record
from jmoraIs.tenancy.context import TenantContextBinder
from jmoraIs.tenancy.domain import TenantContext
from tests.test_patient_context_privacy_ingestion import command, setup


@pytest.fixture(autouse=True)
def tenant_context():
    value=TenantContext("tenant-privacy","org-1","actor-1","CLINICIAN","CLINICAL_DOCUMENTATION","privacy-v1","corr-privacy")
    with TenantContextBinder().bind_tenant(value):yield value


def test_receipt_is_projection_of_distinct_integrity_valid_persisted_record():
    service,repository,_,actor=setup()
    receipt=service.ingest(command(actor))
    record=service._ingestion_records.get(receipt.ingestion_record_id)
    assert record is not None and validate_authorized_ingestion_record(record)
    assert record.patient_context_id==receipt.context_id
    assert record.patient_context_version==receipt.version
    assert repository.get(record.patient_context_id) is not None
    assert not any(key in record.__dict__ for key in ("problems","medications","findings","notes","imaging","clinical_payload"))
    with pytest.raises(FrozenInstanceError):record.source="changed"


def test_forged_integrity_and_broken_context_linkage_are_rejected():
    service,repository,audit,actor=setup();receipt=service.ingest(command(actor));record=service._ingestion_records.get(receipt.ingestion_record_id)
    other_records=type(service._ingestion_records)(repository,audit)
    with pytest.raises(PatientContextPersistenceError,match="integrity"):
        other_records.append_atomic(repository.get(receipt.context_id),replace(record,ingestion_record_id="forged",integrity_hash="0"*64),())
    with pytest.raises(PatientContextPersistenceError,match="linkage"):
        changed=replace(record,ingestion_record_id="forged",patient_context_version=2,integrity_hash="")
        other_records.append_atomic(repository.get(receipt.context_id),sign_authorized_ingestion_record(changed),())


def test_minimization_or_atomic_repository_failure_creates_no_success_artifact():
    service,repository,audit,actor=setup()
    class FailingMinimizer:
        def minimize(self,*_):raise RuntimeError("minimization unavailable")
    service._minimizer=FailingMinimizer()
    with pytest.raises(RuntimeError,match="minimization"):
        service.ingest(command(actor))
    assert repository.latest(command(actor).context.patient_identity.patient_id) is None
    assert service._ingestion_records.by_correlation("corr-privacy")==()

    service,repository,_,actor=setup()
    class FailingAtomicRepository:
        def append_atomic(self,*_):raise RuntimeError("record persistence unavailable")
    service._ingestion_records=FailingAtomicRepository()
    with pytest.raises(RuntimeError,match="record persistence"):
        service.ingest(command(actor))
    assert repository.latest(command(actor).context.patient_identity.patient_id) is None
