from dataclasses import replace
import pytest
from jmoraIs.patient_context import InMemoryPatientContextRepository, PatientContextService, DirectPatientContextWriteProhibited
from jmoraIs.patient_context.application import PatientContextNotFound
from tests.test_patient_context_domain import NOW, context, entry

def test_retrieve_and_version_history_are_append_only():
    repository=InMemoryPatientContextRepository();service=PatientContextService(repository)
    first=context();repository.append(first)
    second=context("context-2",2,first.context_id,entries=(entry(),entry("follow-up")))
    repository.append(second)
    assert service.retrieve(first.patient_identity.patient_id)==second
    assert service.version_history(first.patient_identity.patient_id)==(first,second)
    assert repository.get(first.context_id)==first

def test_direct_application_writes_are_fail_closed():
    service=PatientContextService(InMemoryPatientContextRepository())
    with pytest.raises(DirectPatientContextWriteProhibited): service.create(context())
    with pytest.raises(DirectPatientContextWriteProhibited): service.update(context())

def test_timeline_reconstruction_merges_versions_without_duplicates():
    repository=InMemoryPatientContextRepository();service=PatientContextService(repository);first=context(entries=(entry("onset"),));repository.append(first)
    second=context("context-2",2,first.context_id,entries=(entry("consult"),entry("onset")))
    repository.append(second)
    assert [item.entity_id for item in service.reconstruct_timeline(first.patient_identity.patient_id).entries]==["consult","onset"]
    assert [item.entity_id for item in service.reconstruct_timeline(first.patient_identity.patient_id,through_version=1).entries]==["onset"]

def test_missing_patient_and_invalid_requested_version_fail_closed():
    service=PatientContextService(InMemoryPatientContextRepository())
    with pytest.raises(PatientContextNotFound): service.retrieve("absent")
    with pytest.raises(PatientContextNotFound): service.reconstruct_timeline("absent")
    first=context();service._repository.append(first)
    with pytest.raises(PatientContextNotFound): service.reconstruct_timeline(first.patient_identity.patient_id,through_version=0)

def test_repository_rejects_overwrite_and_invalid_chain():
    repository=InMemoryPatientContextRepository();first=context();repository.append(first)
    with pytest.raises(Exception,match="overwritten"): repository.append(first)
    with pytest.raises(Exception,match="chain"): repository.append(context("v3",3,first.context_id))
