from dataclasses import replace
import hashlib
import os
from uuid import uuid4

import pytest
from alembic import command as alembic_command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from jmoraIs.infrastructure.tenant_database import create_tenant_runtime_engine
from jmoraIs.patient_context.exact_reference import (
    LegacyMissingPersistedPatientContextReference, PatientContextReferenceRejected,
    reference_integrity,
)
from jmoraIs.patient_context.persistence import (
    PostgreSQLPatientContextExactReferenceRepository, PostgreSQLPatientContextRepository,
)
from jmoraIs.tenancy.context import TenantContextBinder
from jmoraIs.tenancy.domain import MissingTenantContext, TenantContext
from tests.test_authorized_ingestion_persistence_postgresql import (
    NOW, compose_service, ingestion_command,
)
from tests.test_patient_context_domain import context


pytestmark = pytest.mark.integration


def signed_change(reference, **changes):
    changed = replace(reference, **changes, integrity_hash="0" * 64)
    return replace(changed, integrity_hash=reference_integrity(changed))


def setup_database():
    url = os.getenv("JMORAIS_TEST_POSTGRES_URL")
    if not url: pytest.skip("JMORAIS_TEST_POSTGRES_URL is required")
    config = Config("alembic.ini"); config.set_main_option("sqlalchemy.url", url)
    alembic_command.upgrade(config, "head")
    return url, create_engine(url, future=True)


def test_owner_issuance_restart_exact_reread_rls_and_append_only():
    url, owner = setup_database(); suffix = uuid4().hex
    tenant = TenantContext("pcref-" + suffix, "pcref-org-" + suffix,
        "pcref-principal-" + suffix, "CLINICIAN", "CLINICAL_DOCUMENTATION",
        "privacy-v1", "corr-pcref-" + suffix)
    patient_id = "pt_" + hashlib.sha256(suffix.encode()).hexdigest()
    with owner.begin() as connection:
        connection.execute(text("INSERT INTO tenants(tenant_id,organization_id,display_name,status,policy_version,created_at) VALUES(:t,:o,'Exact reference','ACTIVE','privacy-v1',:at)"),
            {"t": tenant.tenant_id, "o": tenant.organization_id, "at": NOW})
    writer = create_tenant_runtime_engine(url, runtime_role="jmorais_application_writer")
    binder = TenantContextBinder()
    with binder.bind_tenant(tenant):
        service, contexts, records, audit, actor = compose_service(writer, patient_id, tenant)
        receipt = service.ingest(ingestion_command(patient_id, actor, suffix))
        persisted = contexts.get(receipt.context_id)
        references = PostgreSQLPatientContextExactReferenceRepository(writer, clock=lambda: NOW)
        reference = references.reference_for(persisted)
        assert references.get_exact(reference) == persisted
        reference_id = reference.reference_id
    del service, contexts, records, audit, actor, receipt, persisted, references
    writer.dispose()

    reader = create_tenant_runtime_engine(url, runtime_role="jmorais_application_reader")
    with binder.bind_tenant(tenant):
        restarted = PostgreSQLPatientContextExactReferenceRepository(reader)
        reread = restarted.get_exact(reference)
        assert reread.context_id == reference.context_id
        assert reread.version == reference.version
        assert reread.patient_identity.patient_id == reference.pseudonymous_patient_id
        assert reread.clinical_problems == context(receipt_id := reread.context_id,
            patient_id=patient_id).clinical_problems
    other = TenantContext("other-" + suffix, "other-org-" + suffix, "other-principal",
        "CLINICIAN", "CLINICAL_DOCUMENTATION", "privacy-v1", "corr-other-" + suffix)
    with owner.begin() as connection:
        connection.execute(text("INSERT INTO tenants(tenant_id,organization_id,display_name,status,policy_version,created_at) VALUES(:t,:o,'Other','ACTIVE','privacy-v1',:at)"),
            {"t": other.tenant_id, "o": other.organization_id, "at": NOW})
    with binder.bind_tenant(other), pytest.raises(PatientContextReferenceRejected, match="tenant"):
        PostgreSQLPatientContextExactReferenceRepository(reader).get_exact(reference)
    with pytest.raises(MissingTenantContext):
        PostgreSQLPatientContextExactReferenceRepository(reader).get_exact(reference)
    with pytest.raises(DBAPIError), owner.begin() as connection:
        connection.execute(text("UPDATE patient_context_persisted_references SET policy_version='tampered' WHERE reference_id=:id"), {"id": reference_id})
    with pytest.raises(DBAPIError), owner.begin() as connection:
        connection.execute(text("DELETE FROM patient_context_persisted_references WHERE reference_id=:id"), {"id": reference_id})
    reader.dispose(); owner.dispose()


def test_fabricated_scalar_version_subject_policy_integrity_and_unknown_references_fail_closed():
    url, owner = setup_database(); suffix = uuid4().hex
    tenant = TenantContext("negative-" + suffix, "negative-org-" + suffix,
        "negative-principal", "CLINICIAN", "CLINICAL_DOCUMENTATION", "privacy-v1",
        "negative-corr-" + suffix)
    patient_id = "pt_" + hashlib.sha256(suffix.encode()).hexdigest()
    with owner.begin() as connection:
        connection.execute(text("INSERT INTO tenants(tenant_id,organization_id,display_name,status,policy_version,created_at) VALUES(:t,:o,'Negative','ACTIVE','privacy-v1',:at)"),
            {"t": tenant.tenant_id, "o": tenant.organization_id, "at": NOW})
    writer = create_tenant_runtime_engine(url, runtime_role="jmorais_application_writer")
    with TenantContextBinder().bind_tenant(tenant):
        service, contexts, _, _, actor = compose_service(writer, patient_id, tenant)
        receipt = service.ingest(ingestion_command(patient_id, actor, suffix))
        repository = PostgreSQLPatientContextExactReferenceRepository(writer, clock=lambda: NOW)
        reference = repository.reference_for(contexts.get(receipt.context_id))
        mutations = (
            signed_change(reference, reference_id="pcr_" + "f" * 32),
            signed_change(reference, context_id="wrong-context"),
            signed_change(reference, version=2),
            signed_change(reference, pseudonymous_patient_id="pt_" + "f" * 64),
            signed_change(reference, policy_version="wrong-policy"),
            signed_change(reference, context_integrity_hash="f" * 64),
        )
        for changed in mutations:
            with pytest.raises(PatientContextReferenceRejected): repository.get_exact(changed)
        with pytest.raises(PatientContextReferenceRejected):
            repository.get_exact(replace(reference, integrity_hash="f" * 64))
        with pytest.raises(PatientContextReferenceRejected): repository.get_exact((reference.context_id, 1))
    writer.dispose(); owner.dispose()


def test_legacy_context_without_authorized_ingestion_is_not_upgraded():
    url, owner = setup_database(); suffix = uuid4().hex
    legacy = context("legacy-context-" + suffix,
        patient_id="pt_" + hashlib.sha256(("legacy" + suffix).encode()).hexdigest())
    PostgreSQLPatientContextRepository(owner).append(legacy)
    tenant = TenantContext("legacy-internal", "legacy-internal", "legacy-principal",
        "CLINICIAN", "CLINICAL_DOCUMENTATION", "privacy-v1", "legacy-corr")
    with TenantContextBinder().bind_tenant(tenant), pytest.raises(
            LegacyMissingPersistedPatientContextReference,
            match="LEGACY_MISSING_PERSISTED_PATIENT_CONTEXT_REFERENCE"):
        PostgreSQLPatientContextExactReferenceRepository(owner).reference_for(legacy)
    owner.dispose()
