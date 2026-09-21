import os
from dataclasses import replace
from uuid import uuid4
import pytest
from alembic import command
from alembic.config import Config
from jmoraIs.clinical_state.persistence import PostgreSQLClinicalStateRepository
from jmoraIs.infrastructure.tenant_database import create_tenant_runtime_engine
from jmoraIs.medical_documents import PostgreSQLGovernedDocumentClinicalStateAdapter,DocumentFactReference
from jmoraIs.tenancy.context import TenantContextBinder
from jmoraIs.tenancy.domain import TenantContext
from tests.test_governed_document_clinical_state import rich_state

def test_restart_document_fact_reconstruction_and_rls():
    url=os.getenv("JMORAIS_TEST_POSTGRES_URL")
    if not url:pytest.skip("JMORAIS_TEST_POSTGRES_URL is required")
    config=Config("alembic.ini");config.set_main_option("sqlalchemy.url",url);command.upgrade(config,"head")
    suffix=uuid4().hex;binder=TenantContextBinder();writer=create_tenant_runtime_engine(url,runtime_role="jmorais_application_writer")
    a=TenantContext(f"tenant-a-{suffix}",f"org-a-{suffix}","principal","CLINICAL_REVIEWER","CLINICAL_VALIDATION","policy","corr-a")
    b=TenantContext(f"tenant-b-{suffix}",f"org-b-{suffix}","principal","CLINICAL_REVIEWER","CLINICAL_VALIDATION","policy","corr-b")
    value=replace(rich_state(),state_id=f"state-doc-{suffix}",pseudonymous_patient_id="pt_"+suffix*2)
    with binder.bind_tenant(a):PostgreSQLClinicalStateRepository(writer).append(value)
    reader=create_tenant_runtime_engine(url,runtime_role="jmorais_application_reader");adapter=PostgreSQLGovernedDocumentClinicalStateAdapter(reader)
    with binder.bind_tenant(a):facts=adapter.facts(value.state_id)
    assert facts and all(isinstance(x,DocumentFactReference) for x in facts) and all(x.source_reference_id==value.state_id for x in facts)
    with binder.bind_tenant(b):assert adapter.facts(value.state_id)==()
    assert adapter.facts(value.state_id)==()
