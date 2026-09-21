import os
from dataclasses import replace
from uuid import uuid4
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine,text
from sqlalchemy.exc import DBAPIError
from jmoraIs.guideline_engine import *
from jmoraIs.infrastructure.tenant_database import create_tenant_runtime_engine
from jmoraIs.tenancy.context import TenantContextBinder
from jmoraIs.tenancy.domain import TenantContext
from tests.test_guideline_engine import NOW,ready_input,setup
pytestmark=pytest.mark.integration
@pytest.fixture(scope="module")
def engine():
    url=os.getenv("JMORAIS_TEST_POSTGRES_URL")
    if not url:pytest.skip("JMORAIS_TEST_POSTGRES_URL is required")
    config=Config("alembic.ini");config.set_main_option("sqlalchemy.url",url);command.upgrade(config,"head")
    value=create_engine(url,future=True);yield value;value.dispose()
def test_postgresql_restart_reconstruction_and_append_only(engine):
    input_value=ready_input();suffix=uuid4().hex;subject="pt_"+suffix*2;input_value=__import__("dataclasses").replace(input_value,subject_reference=subject,input_id="ri_"+suffix*2)
    memory_engine,_,_=setup();generated=memory_engine.create_recommendation_set(input_value)
    repository=PostgreSQLRecommendationRepository(engine);audit=PostgreSQLRecommendationAuditAdapter(engine);repository.append(generated)
    event=RecommendationAuditEvent("gr_"+uuid4().hex*2,subject,generated.set_id,RecommendationAuditType.GENERATION,NOW,"engine","GENERATED",tuple(item.recommendation_id for item in generated.recommendations),generated.policy_version);audit.append(event)
    restarted=PostgreSQLRecommendationRepository(engine);restarted_audit=PostgreSQLRecommendationAuditAdapter(engine)
    assert restarted.history(subject)==(generated,) and restarted.latest(subject)==generated
    assert restarted_audit.history(subject)==(event,)
    with pytest.raises(DBAPIError),engine.begin() as connection:connection.execute(text("UPDATE guideline_recommendation_versions SET readiness='ALTERED' WHERE set_id=:id"),{"id":generated.set_id})
    with pytest.raises(DBAPIError),engine.begin() as connection:connection.execute(text("DELETE FROM guideline_recommendation_versions WHERE set_id=:id"),{"id":generated.set_id})
    with pytest.raises(DBAPIError),engine.begin() as connection:connection.execute(text("DELETE FROM guideline_recommendation_audit WHERE subject_reference=:id"),{"id":subject})

def test_owner_issued_exact_reference_restart_integrity_and_rls(engine):
    suffix=uuid4().hex;tenant=f"guideline-ref-{suffix}";other=f"guideline-other-{suffix}"
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO tenants(tenant_id,organization_id,display_name,status,policy_version,created_at) VALUES(:t,:o,'Guideline exact','ACTIVE','iam-policy-v1',:at)"),{"t":tenant,"o":"org-"+tenant,"at":NOW})
        connection.execute(text("INSERT INTO tenants(tenant_id,organization_id,display_name,status,policy_version,created_at) VALUES(:t,:o,'Other','ACTIVE','iam-policy-v1',:at)"),{"t":other,"o":"org-"+other,"at":NOW})
    binder=TenantContextBinder();context=lambda value:TenantContext(value,"org-"+value,"principal","INTERNAL_SERVICE","CLINICAL_VALIDATION","iam-policy-v1","corr-"+value)
    runtime_url=os.environ["JMORAIS_TEST_POSTGRES_URL"]
    writer=create_tenant_runtime_engine(runtime_url,runtime_role="jmorais_application_writer")
    source=replace(ready_input(),subject_reference="pt_"+suffix*2,input_id="ri_"+suffix*2)
    generated=setup()[0].create_recommendation_set(source)
    with binder.bind_tenant(context(tenant)):
        repository=PostgreSQLRecommendationRepository(writer);repository.append(generated);reference=repository.reference_for(generated)
    del repository,generated
    reader=create_tenant_runtime_engine(runtime_url,runtime_role="jmorais_application_reader")
    with binder.bind_tenant(context(tenant)):
        exact=PostgreSQLRecommendationRepository(reader).get_exact(reference)
        assert exact.set_id==reference.set_id and exact.set_version==reference.set_version
        assert exact.subject_reference==reference.subject_reference and exact.policy_version==reference.policy_version
        with pytest.raises(GuidelineBoundaryRejected):PostgreSQLRecommendationRepository(reader).get_exact(replace(reference,set_version=2))
        with pytest.raises(GuidelineBoundaryRejected):PostgreSQLRecommendationRepository(reader).get_exact(replace(reference,integrity_hash="0"*64))
        with pytest.raises(GuidelineBoundaryRejected):PostgreSQLRecommendationRepository(reader).get_exact(PersistedGuidelineRecommendationSetReference("gsr_"+uuid4().hex,reference.set_id,reference.set_version,reference.subject_reference,tenant,reference.policy_version,reference.integrity_hash,reference.issued_at))
    with binder.bind_tenant(context(other)):
        with pytest.raises(GuidelineBoundaryRejected):PostgreSQLRecommendationRepository(reader).get_exact(reference)
    with pytest.raises(Exception):PostgreSQLRecommendationRepository(reader).get_exact(reference)
    writer.dispose();reader.dispose()
