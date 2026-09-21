import os
from dataclasses import replace
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine,text
from sqlalchemy.exc import DBAPIError,IntegrityError

from jmoraIs.infrastructure.tenant_database import create_tenant_runtime_engine
from jmoraIs.llm_gateway import *
from jmoraIs.tenancy.context import TenantContextBinder
from jmoraIs.tenancy.domain import TenantContext
from tests.test_llm_gateway import NOW,request,response,template

pytestmark=pytest.mark.integration

def _tenant(tenant,correlation,principal="stage13-service",purpose="CLINICAL_VALIDATION",policy="MIP-10.1"):
    return TenantContext(tenant,"org-"+tenant,principal,"INTERNAL_SERVICE",purpose,policy,correlation)

def test_context_gateway_restart_linkage_rls_append_only_and_legacy():
    url=os.getenv("JMORAIS_TEST_POSTGRES_URL")
    if not url:pytest.skip("JMORAIS_TEST_POSTGRES_URL is required")
    config=Config("alembic.ini");config.set_main_option("sqlalchemy.url",url);command.upgrade(config,"head")
    suffix=uuid4().hex;owner=create_engine(url,future=True);binder=TenantContextBinder()
    prompts=PostgreSQLPromptRepository(owner);registration=PostgreSQLPromptAuditRepository(owner)
    version=PromptGovernanceService(prompts,registration,clock=lambda:NOW).register(replace(template(),template_id="context-"+suffix),created_by="architect")
    tenant_a="context-a-"+suffix;tenant_b="context-b-"+suffix;correlation="corr-context-"+suffix;request_id="request-context-"+suffix
    writer=create_tenant_runtime_engine(url,runtime_role="jmorais_application_writer")
    contexts=PostgreSQLLLMInvocationContextRepository(writer);invocations=PostgreSQLInvocationRepository(writer);audits=PostgreSQLPromptAuditRepository(writer)
    gateway=CanonicalLLMGateway(prompts,audits,invocations,contexts,(MockProviderAdapter((response(),)),),clock=lambda:NOW)
    with binder.bind_tenant(_tenant(tenant_a,correlation)):
        result=gateway.invoke(replace(request(version),request_id=request_id))
        original_context=contexts.get(request_id);original_invocation=invocations.history(request_id)[0];original_audit=audits.history(request_id)[0]
    assert original_context==LLMInvocationContext(correlation,tenant_a,"stage13-service","CLINICAL_VALIDATION","MIP-10.1",request_id,NOW)
    assert original_context.request_id==original_invocation.request_id==original_audit.request_id
    assert original_context.correlation_id==original_invocation.correlation_id==original_audit.correlation_id
    assert original_context.policy_version==original_invocation.policy_version==original_audit.policy_version
    assert result.classification is original_invocation.output_classification
    writer.dispose();del gateway,contexts,invocations,audits,result

    reader=create_tenant_runtime_engine(url,runtime_role="jmorais_application_reader")
    restarted_contexts=PostgreSQLLLMInvocationContextRepository(reader);restarted_invocations=PostgreSQLInvocationRepository(reader);restarted_audits=PostgreSQLPromptAuditRepository(reader)
    with binder.bind_tenant(_tenant(tenant_a,correlation)):
        reread_context=restarted_contexts.get(request_id);reread_invocation=restarted_invocations.history(request_id)[0];reread_audit=restarted_audits.history(request_id)[0]
        assert restarted_contexts.history_by_correlation(correlation)==(original_context,)
    assert reread_context==original_context and reread_context is not original_context
    assert reread_invocation==original_invocation and reread_audit==original_audit
    assert (reread_invocation.temperature,reread_invocation.seed)==(reread_audit.temperature,reread_audit.seed)==(.2,7)
    with binder.bind_tenant(_tenant(tenant_b,correlation)):
        assert restarted_contexts.get(request_id) is None
        assert restarted_contexts.history_by_correlation(correlation)==()
        tenant_b_context=replace(original_context,tenant_id=tenant_b,principal_id="stage13-service")
        PostgreSQLLLMInvocationContextRepository(writer).append(tenant_b_context)
        assert restarted_contexts.get(request_id)==tenant_b_context
    with binder.bind_tenant(_tenant(tenant_a,correlation)):
        assert restarted_contexts.get(request_id)==original_context
    assert restarted_contexts.get(request_id) is None

    for index,change in enumerate((
        {"principal_id":"forged-principal"},{"purpose":"RESEARCH"},{"policy_version":"future-policy"},
        {"correlation_id":"corr-forged-"+suffix},{"tenant_id":tenant_b},
    )):
        wrong=replace(original_context,request_id=f"wrong-{index}-{suffix}",**change)
        with binder.bind_tenant(_tenant(tenant_a,correlation)),pytest.raises(LLMPolicyRejected,match="does not match"):
            PostgreSQLLLMInvocationContextRepository(reader).append(wrong)
    with pytest.raises(LLMPolicyRejected,match="trusted tenant context"):
        PostgreSQLLLMInvocationContextRepository(reader).append(replace(original_context,request_id="missing-tenant-"+suffix))
    without_context=replace(original_invocation,invocation_id="inv_"+uuid4().hex*2,request_id="missing-context-"+suffix)
    with binder.bind_tenant(_tenant(tenant_a,correlation)),pytest.raises(LLMPolicyRejected,match="persisted invocation context"):
        PostgreSQLInvocationRepository(writer).append(without_context)
    with binder.bind_tenant(_tenant(tenant_a,correlation)),pytest.raises(LLMPolicyRejected,match="correlation mismatch"):
        PostgreSQLInvocationRepository(writer).append(replace(original_invocation,invocation_id="inv_"+uuid4().hex*2,correlation_id="corr-mismatch-"+suffix))
    with binder.bind_tenant(_tenant(tenant_a,correlation)),pytest.raises(LLMPolicyRejected,match="policy mismatch"):
        PostgreSQLInvocationRepository(writer).append(replace(original_invocation,invocation_id="inv_"+uuid4().hex*2,policy_version="future-policy"))
    with binder.bind_tenant(_tenant(tenant_a,correlation)),pytest.raises(IntegrityError):
        PostgreSQLLLMInvocationContextRepository(writer).append(original_context)
    with pytest.raises(DBAPIError),owner.begin() as connection:
        connection.execute(text("UPDATE llm_invocation_contexts SET purpose='ALTERED' WHERE request_id=:id"),{"id":request_id})
    with pytest.raises(DBAPIError),owner.begin() as connection:
        connection.execute(text("DELETE FROM llm_invocation_contexts WHERE request_id=:id"),{"id":request_id})
    assert PostgreSQLLLMInvocationContextRepository(owner).status("legacy-no-context-"+suffix) is InvocationContextPersistenceStatus.LEGACY_MISSING_INVOCATION_CONTEXT
    with owner.connect() as connection:
        assert connection.execute(text("SELECT rolbypassrls FROM pg_roles WHERE rolname='jmorais_application_reader'")).scalar_one() is False
    reader.dispose();owner.dispose()
