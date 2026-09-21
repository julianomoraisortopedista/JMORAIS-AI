from dataclasses import replace
import hashlib
import os
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from jmoraIs.clinical_state import (
    AuthorizedPatientContextQueryAdapter, DeterministicClinicalNormalizer,
    PatientClinicalStateService, PostgreSQLClinicalStateAuditAdapter,
    PostgreSQLClinicalStateExactReferenceRepository, PostgreSQLClinicalStateRepository,
)
from jmoraIs.clinical_state.exact_reference import (
    ClinicalStateReferenceRejected, ClinicalStateTimelineReferenceRejected,
    PersistedClinicalStateReference, PersistedClinicalStateTimelineReference,
    reference_integrity, timeline_integrity,
)
from jmoraIs.infrastructure.tenant_database import create_tenant_runtime_engine
from jmoraIs.tenancy.context import TenantContextBinder
from jmoraIs.tenancy.domain import MissingTenantContext, TenantContext
from tests.test_clinical_state import rich_context
from tests.test_patient_context_domain import NOW


pytestmark = pytest.mark.integration


def setup_database():
    url = os.getenv("JMORAIS_TEST_POSTGRES_URL")
    if not url: pytest.skip("JMORAIS_TEST_POSTGRES_URL is required")
    config = Config("alembic.ini"); config.set_main_option("sqlalchemy.url", url); command.upgrade(config, "head")
    return url, create_engine(url, future=True)


def tenant_for(suffix, prefix="state-ref"):
    return TenantContext(prefix + "-" + suffix, prefix + "-org-" + suffix,
        prefix + "-principal", "CLINICIAN", "CLINICAL_DOCUMENTATION",
        "privacy-v1", prefix + "-corr-" + suffix)


def insert_tenant(owner, tenant):
    with owner.begin() as connection:
        connection.execute(text("""INSERT INTO tenants
          (tenant_id,organization_id,display_name,status,policy_version,created_at)
          VALUES(:tenant,:organization,'Clinical state exact','ACTIVE',:policy,:at)"""),
          {"tenant": tenant.tenant_id, "organization": tenant.organization_id,
           "policy": tenant.policy_version, "at": NOW})


def persisted_states(writer, tenant, suffix):
    patient_id = "pt_" + hashlib.sha256(suffix.encode()).hexdigest()
    context = rich_context("state-ref-context-" + suffix)
    context = replace(context, patient_identity=replace(context.patient_identity, patient_id=patient_id),
                      timeline=replace(context.timeline, patient_id=patient_id))
    repository = PostgreSQLClinicalStateRepository(writer)
    service = PatientClinicalStateService(AuthorizedPatientContextQueryAdapter(lambda patient: (context,)),
        repository, PostgreSQLClinicalStateAuditAdapter(writer), DeterministicClinicalNormalizer(), clock=lambda: NOW)
    first = service.build_current_state(patient_id)
    second = service.request_review(patient_id, actor_id="reviewer", source_event_id="request",
                                    provenance="review:request")
    return first, second


def signed(reference, **changes):
    changed = replace(reference, **changes, integrity_hash="0" * 64)
    return replace(changed, integrity_hash=reference_integrity(changed))


def test_exact_state_and_timeline_restart_reread_rls_append_only_and_no_scan():
    url, owner = setup_database(); suffix = uuid4().hex; tenant = tenant_for(suffix); insert_tenant(owner, tenant)
    writer = create_tenant_runtime_engine(url, runtime_role="jmorais_application_writer")
    binder = TenantContextBinder()
    with binder.bind_tenant(tenant):
        first, second = persisted_states(writer, tenant, suffix)
        references = PostgreSQLClinicalStateExactReferenceRepository(writer, clock=lambda: NOW)
        first_ref = references.reference_for(first); second_ref = references.reference_for(second)
        timeline_ref = references.timeline_reference_for((first_ref, second_ref))
        assert references.get_exact(second_ref) == second
        assert references.get_timeline_exact(timeline_ref) == (first, second)
    del first, second, references
    writer.dispose()

    reader = create_tenant_runtime_engine(url, runtime_role="jmorais_application_reader")
    with binder.bind_tenant(tenant):
        restarted = PostgreSQLClinicalStateExactReferenceRepository(reader)
        exact = restarted.get_exact(second_ref)
        timeline = restarted.get_timeline_exact(timeline_ref)
    assert exact.state_id == second_ref.state_id and exact.state_version == 2
    assert tuple(item.state_id for item in timeline) == (first_ref.state_id, second_ref.state_id)
    assert tuple(item.state_version for item in timeline) == (1, 2)

    other = tenant_for(suffix, "other-state-ref"); insert_tenant(owner, other)
    with binder.bind_tenant(other), pytest.raises((ClinicalStateReferenceRejected, ClinicalStateTimelineReferenceRejected)):
        PostgreSQLClinicalStateExactReferenceRepository(reader).get_exact(second_ref)
    with pytest.raises(MissingTenantContext):
        PostgreSQLClinicalStateExactReferenceRepository(reader).get_exact(second_ref)
    for table, identifier, value in (
        ("clinical_state_persisted_references", "reference_id", first_ref.reference_id),
        ("clinical_state_timeline_references", "timeline_reference_id", timeline_ref.timeline_reference_id),
        ("clinical_state_timeline_reference_members", "timeline_reference_id", timeline_ref.timeline_reference_id)):
        with pytest.raises(DBAPIError), owner.begin() as connection:
            connection.execute(text(f"UPDATE {table} SET tenant_id='tampered' WHERE {identifier}=:id"), {"id": value})
        with pytest.raises(DBAPIError), owner.begin() as connection:
            connection.execute(text(f"DELETE FROM {table} WHERE {identifier}=:id"), {"id": value})
    reader.dispose(); owner.dispose()


def test_fabrication_scalar_mismatch_integrity_order_duplicate_gap_and_policy_fail_closed():
    url, owner = setup_database(); suffix = uuid4().hex; tenant = tenant_for(suffix, "negative-state-ref"); insert_tenant(owner, tenant)
    writer = create_tenant_runtime_engine(url, runtime_role="jmorais_application_writer")
    with TenantContextBinder().bind_tenant(tenant):
        first, second = persisted_states(writer, tenant, suffix)
        repository = PostgreSQLClinicalStateExactReferenceRepository(writer, clock=lambda: NOW)
        first_ref = repository.reference_for(first); second_ref = repository.reference_for(second)
        valid_timeline = repository.timeline_reference_for((first_ref, second_ref))
        for changed in (
            signed(first_ref, reference_id="csr_" + "f" * 32),
            signed(first_ref, state_id="wrong-state"), signed(first_ref, state_version=3,
                predecessor_reference_id=first_ref.reference_id, predecessor_state_version=2),
            signed(first_ref, pseudonymous_patient_id="pt_" + "f" * 64),
            signed(first_ref, tenant_id="wrong-tenant"), signed(first_ref, policy_version="wrong-policy"),
            signed(first_ref, state_integrity_hash="f" * 64),
        ):
            with pytest.raises(ClinicalStateReferenceRejected): repository.get_exact(changed)
        with pytest.raises(ClinicalStateReferenceRejected): repository.get_exact((first_ref.state_id, 1))
        with pytest.raises(ClinicalStateReferenceRejected): repository.get_exact(replace(first_ref, integrity_hash="f" * 64))
        for members in ((second_ref, first_ref), (first_ref, first_ref), (second_ref,)):
            unsigned = replace(valid_timeline, timeline_reference_id="cst_" + uuid4().hex,
                               state_references=members, integrity_hash="0" * 64)
            candidate = replace(unsigned, integrity_hash=timeline_integrity(unsigned))
            with pytest.raises(ClinicalStateTimelineReferenceRejected): repository.get_timeline_exact(candidate)
        fabricated = replace(valid_timeline, timeline_reference_id="cst_" + "f" * 32, integrity_hash="0" * 64)
        fabricated = replace(fabricated, integrity_hash=timeline_integrity(fabricated))
        with pytest.raises(ClinicalStateTimelineReferenceRejected): repository.get_timeline_exact(fabricated)
    writer.dispose(); owner.dispose()
