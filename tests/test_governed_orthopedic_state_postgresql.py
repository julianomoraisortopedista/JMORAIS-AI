import os
from uuid import uuid4
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from jmoraIs.clinical_state.persistence import PostgreSQLClinicalStateRepository
from jmoraIs.infrastructure.tenant_database import create_tenant_runtime_engine
from jmoraIs.orthopedic_intelligence import PostgreSQLGovernedOrthopedicStateQueryAdapter
from jmoraIs.tenancy.context import TenantContextBinder
from jmoraIs.tenancy.domain import TenantContext
from tests.test_governed_orthopedic_state import NOW,state,terminology_records
from tests.test_terminology import version
from jmoraIs.terminology import ClinicalTerminologyService,DeterministicUcumAdapter,PostgreSQLTerminologyAuditAdapter,PostgreSQLTerminologyRepository

def test_restart_reconstruction_and_rls_isolation():
    url=os.getenv("JMORAIS_TEST_POSTGRES_URL")
    if not url:pytest.skip("JMORAIS_TEST_POSTGRES_URL is required")
    config=Config("alembic.ini");config.set_main_option("sqlalchemy.url",url);command.upgrade(config,"head")
    suffix=uuid4().hex;term_version=f"1.0-{suffix}";owner=create_engine(url,future=True);terms=PostgreSQLTerminologyRepository(owner);release=__import__("dataclasses").replace(version(),version=term_version,version_id=f"version-{suffix}")
    try:terms.append(release.version_id,release)
    except Exception:pass
    for item in terminology_records():
        item=__import__("dataclasses").replace(item,version=term_version,codes=tuple(__import__("dataclasses").replace(code,version=term_version) for code in item.codes))
        try:terms.append(item.canonical_id,item)
        except Exception:pass
    terminology=ClinicalTerminologyService(terms,PostgreSQLTerminologyAuditAdapter(owner),DeterministicUcumAdapter(),clock=lambda:NOW)
    runtime=create_tenant_runtime_engine(url,runtime_role="jmorais_application_writer");binder=TenantContextBinder()
    tenant_a=TenantContext(f"tenant-a-{suffix}",f"org-a-{suffix}","principal","CLINICAL_REVIEWER","CLINICAL_VALIDATION","policy","corr-a")
    tenant_b=TenantContext(f"tenant-b-{suffix}",f"org-b-{suffix}","principal","CLINICAL_REVIEWER","CLINICAL_VALIDATION","policy","corr-b")
    value=state();value=__import__("dataclasses").replace(value,state_id=f"state-{suffix}",pseudonymous_patient_id="pt_"+suffix*2)
    with binder.bind_tenant(tenant_a):PostgreSQLClinicalStateRepository(runtime).append(value)
    restarted=create_tenant_runtime_engine(url,runtime_role="jmorais_application_reader")
    with binder.bind_tenant(tenant_a):view=PostgreSQLGovernedOrthopedicStateQueryAdapter(restarted,terminology,term_version).get(value.state_id)
    assert view.state_reference_id==value.state_id
    with binder.bind_tenant(tenant_b):assert PostgreSQLGovernedOrthopedicStateQueryAdapter(restarted,terminology,term_version).get(value.state_id) is None
    assert PostgreSQLGovernedOrthopedicStateQueryAdapter(restarted,terminology,term_version).get(value.state_id) is None
