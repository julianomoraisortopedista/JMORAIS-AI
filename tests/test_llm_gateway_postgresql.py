import os
from uuid import uuid4
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine,text
from sqlalchemy.exc import DBAPIError
from jmoraIs.llm_gateway import *
from tests.test_llm_gateway import NOW,template,model
from jmoraIs.infrastructure.tenant_database import create_tenant_runtime_engine
from jmoraIs.tenancy.context import TenantContextBinder
from jmoraIs.tenancy.domain import TenantContext
pytestmark=pytest.mark.integration
@pytest.fixture(scope="module")
def engine():
    url=os.getenv("JMORAIS_TEST_POSTGRES_URL")
    if not url:pytest.skip("JMORAIS_TEST_POSTGRES_URL is required")
    config=Config("alembic.ini");config.set_main_option("sqlalchemy.url",url);command.upgrade(config,"head");value=create_engine(url,future=True);yield value;value.dispose()
def test_postgresql_prompt_invocation_audit_restart_and_append_only(engine):
    suffix=uuid4().hex;prompt_repo=PostgreSQLPromptRepository(engine);audit_repo=PostgreSQLPromptAuditRepository(engine);inv_repo=PostgreSQLInvocationRepository(engine);governance=PromptGovernanceService(prompt_repo,audit_repo,clock=lambda:NOW);version=governance.register(__import__("dataclasses").replace(template(),template_id="template-"+suffix),created_by="architect")
    usage=TokenUsage(10,5,0,15);cost=CostReport("USD",.01,.02,.03,"MIP-10.1");request_id="request-"+suffix
    correlation="corr-"+suffix
    context=LLMInvocationContext(correlation,"legacy-internal","llm-test-service","CLINICAL_VALIDATION","MIP-10.1",request_id,NOW)
    with TenantContextBinder().bind_tenant(TenantContext("legacy-internal","legacy-internal","llm-test-service","INTERNAL_SERVICE","CLINICAL_VALIDATION","MIP-10.1",correlation)):PostgreSQLLLMInvocationContextRepository(engine).append(context)
    invocation=LLMInvocation("inv_"+suffix*2,request_id,version.prompt_version_id,LLMProvider.MOCK,"mock",InvocationStatus.SUCCEEDED,1,5,usage,cost,"request-hash","response-hash",NOW,"MIP-10.1",correlation,LLMOutputClassification.APPROVED_FOR_REVIEW,0,1);inv_repo.append(invocation)
    event=PromptAudit("pa_"+suffix*2,PromptAuditType.INVOCATION,request_id,version.prompt_version_id,LLMProvider.MOCK,"mock",0,1,usage,cost,5,0,InvocationStatus.SUCCEEDED,"request-hash","response-hash",NOW,"MIP-10.1",correlation);audit_repo.append(event)
    assert PostgreSQLPromptRepository(engine).get(version.prompt_version_id)==version and PostgreSQLPromptRepository(engine).history(version.template_id)==(version,)
    assert PostgreSQLInvocationRepository(engine).history(request_id)==(invocation,) and PostgreSQLPromptAuditRepository(engine).history(request_id)==(event,)
    assert PostgreSQLInvocationRepository(engine).history_by_correlation(correlation)==(invocation,)
    assert PostgreSQLPromptAuditRepository(engine).history_by_correlation(correlation)==(event,)
    for table,key,column in (("llm_prompt_versions",version.prompt_version_id,"prompt_version_id"),("llm_prompt_audit",event.event_id,"event_id"),("llm_invocations",invocation.invocation_id,"invocation_id"),("llm_invocation_contexts",context.request_id,"request_id")):
        with pytest.raises(DBAPIError),engine.begin() as c:c.execute(text(f"UPDATE {table} SET policy_version='ALTERED' WHERE {column}=:id"),{"id":key})
        with pytest.raises(DBAPIError),engine.begin() as c:c.execute(text(f"DELETE FROM {table} WHERE {column}=:id"),{"id":key})

@pytest.mark.parametrize("classification,status",[
    (LLMOutputClassification.DRAFT,InvocationStatus.SUCCEEDED),
    (LLMOutputClassification.REVIEW_REQUIRED,InvocationStatus.SUCCEEDED),
    (LLMOutputClassification.BLOCKED,InvocationStatus.BLOCKED),
    (LLMOutputClassification.APPROVED_FOR_REVIEW,InvocationStatus.SUCCEEDED),
])
def test_all_canonical_output_classifications_are_persisted_without_status_inference(engine,classification,status):
    suffix=uuid4().hex;value=LLMInvocation("inv_"+suffix*2,"request-class-"+suffix,"prompt-version",
        LLMProvider.MOCK,"mock",status,1,7,TokenUsage(1,1,0,2),CostReport("USD",0,0,0,"MIP-10.1"),
        "request-hash","response-hash",NOW,"MIP-10.1","corr-class-"+suffix,classification,.3,11)
    with TenantContextBinder().bind_tenant(TenantContext("legacy-internal","legacy-internal","llm-test-service","INTERNAL_SERVICE","CLINICAL_VALIDATION","MIP-10.1",value.correlation_id)):PostgreSQLLLMInvocationContextRepository(engine).append(LLMInvocationContext(value.correlation_id,"legacy-internal","llm-test-service","CLINICAL_VALIDATION","MIP-10.1",value.request_id,NOW))
    repository=PostgreSQLInvocationRepository(engine);repository.append(value)
    assert repository.history(value.request_id)==(value,)
