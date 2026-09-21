import os
from dataclasses import replace
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config

from jmoraIs.audit_defense import PostgreSQLGovernedAuditClinicalStateAdapter
from jmoraIs.clinical_state.persistence import PostgreSQLClinicalStateRepository
from jmoraIs.infrastructure.tenant_database import create_tenant_runtime_engine
from jmoraIs.tenancy.context import TenantContextBinder
from jmoraIs.tenancy.domain import TenantContext
from tests.test_audit_defense import setup
from tests.test_governed_audit_clinical_state import governed_state


pytestmark = pytest.mark.integration


def _context(tenant, organization, correlation):
    return TenantContext(tenant, organization, "stage12-service", "INTERNAL_SERVICE",
                         "CLINICAL_VALIDATION", "stage12-policy", correlation)


def test_restart_rls_and_actual_audit_defense_clinical_support_path():
    url = os.getenv("JMORAIS_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("JMORAIS_TEST_POSTGRES_URL is required")
    config = Config("alembic.ini"); config.set_main_option("sqlalchemy.url", url); command.upgrade(config, "head")
    suffix = uuid4().hex; binder = TenantContextBinder()
    tenant_a = _context(f"tenant-a-{suffix}", f"org-a-{suffix}", "corr-a")
    tenant_b = _context(f"tenant-b-{suffix}", f"org-b-{suffix}", "corr-b")
    state = replace(governed_state(), state_id=f"state-audit-{suffix}",
                    pseudonymous_patient_id="pt_" + suffix * 2)
    writer = create_tenant_runtime_engine(url, runtime_role="jmorais_application_writer")
    with binder.bind_tenant(tenant_a):
        PostgreSQLClinicalStateRepository(writer).append(state)
    writer.dispose(); del writer

    reader = create_tenant_runtime_engine(url, runtime_role="jmorais_application_reader")
    adapter = PostgreSQLGovernedAuditClinicalStateAdapter(reader)
    with binder.bind_tenant(tenant_a):
        first = adapter.facts(state.state_id)
    reader.dispose(); del reader, adapter

    restarted = create_tenant_runtime_engine(url, runtime_role="jmorais_application_reader")
    restarted_adapter = PostgreSQLGovernedAuditClinicalStateAdapter(restarted)
    with binder.bind_tenant(tenant_a):
        reread = restarted_adapter.facts(state.state_id)
    assert reread == first and reread is not first and reread[0] is not first[0]
    with binder.bind_tenant(tenant_b):
        assert restarted_adapter.facts(state.state_id) == ()
    assert restarted_adapter.facts(state.state_id) == ()

    service, _, _, reasoning_input = setup()
    service._clinical = restarted_adapter
    governed_input = replace(
        reasoning_input,
        patient_clinical_state=replace(reasoning_input.patient_clinical_state,
                                       reference_id=state.state_id,
                                       clinical_state_version=state.state_version),
    )
    with binder.bind_tenant(tenant_a):
        clinical_support = service._clinical_support(governed_input)
    assert clinical_support and all(item.clinical_state_reference_id == state.state_id for item in clinical_support)
    restarted.dispose()
