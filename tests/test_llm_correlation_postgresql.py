import json
import os
from dataclasses import replace
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from jmoraIs.infrastructure.tenant_database import create_tenant_runtime_engine
from jmoraIs.llm_gateway import (
    CanonicalLLMGateway, LLMGatewayJsonCodec, LLMInvocation, LLMPolicyRejected,
    MockProviderAdapter, PostgreSQLInvocationRepository, PostgreSQLLLMInvocationContextRepository, PostgreSQLPromptAuditRepository,
    PostgreSQLPromptRepository, PromptGovernanceService,
)
from jmoraIs.tenancy.context import TenantContextBinder
from jmoraIs.tenancy.domain import TenantContext
from tests.test_llm_gateway import NOW, request, response, template

pytestmark = pytest.mark.integration


def _context(tenant, correlation):
    return TenantContext(tenant, "org-" + tenant, "llm-service", "INTERNAL_SERVICE",
                         "CLINICAL_VALIDATION", "MIP-10.1", correlation)


def test_canonical_correlation_restart_rls_collision_legacy_and_append_only():
    url=os.getenv("JMORAIS_TEST_POSTGRES_URL")
    if not url:pytest.skip("JMORAIS_TEST_POSTGRES_URL is required")
    config=Config("alembic.ini");config.set_main_option("sqlalchemy.url",url);command.upgrade(config,"head")
    suffix=uuid4().hex;owner=create_engine(url,future=True);binder=TenantContextBinder()
    correlation="corr-stage13-"+suffix;tenant_a="llm-a-"+suffix;tenant_b="llm-b-"+suffix
    prompts=PostgreSQLPromptRepository(owner);registration_audit=PostgreSQLPromptAuditRepository(owner)
    version=PromptGovernanceService(prompts,registration_audit,clock=lambda:NOW).register(
        replace(template(),template_id="prompt-correlation-"+suffix),created_by="architect")

    writer=create_tenant_runtime_engine(url,runtime_role="jmorais_application_writer")
    invocations=PostgreSQLInvocationRepository(writer);contexts=PostgreSQLLLMInvocationContextRepository(writer);audit=PostgreSQLPromptAuditRepository(writer)
    first_request=replace(request(version),request_id="request-a-"+suffix)
    gateway=CanonicalLLMGateway(prompts,audit,invocations,contexts,(MockProviderAdapter((response(),)),),clock=lambda:NOW)
    with binder.bind_tenant(_context(tenant_a,correlation)):
        result=gateway.invoke(first_request)
        first_invocation=invocations.history(first_request.request_id)[0]
        first_audit=audit.history(first_request.request_id)[0]
    assert not result.externally_actionable
    assert first_invocation.correlation_id==first_audit.correlation_id==correlation
    assert first_invocation.request_id!=correlation

    second_request=replace(request(version),request_id="request-b-"+suffix)
    second_gateway=CanonicalLLMGateway(prompts,audit,invocations,contexts,(MockProviderAdapter((response(),)),),clock=lambda:NOW)
    with binder.bind_tenant(_context(tenant_b,correlation)):second_gateway.invoke(second_request)
    writer.dispose();del gateway,second_gateway,invocations,audit,result

    reader=create_tenant_runtime_engine(url,runtime_role="jmorais_application_reader")
    restarted_invocations=PostgreSQLInvocationRepository(reader);restarted_audit=PostgreSQLPromptAuditRepository(reader)
    with binder.bind_tenant(_context(tenant_a,correlation)):
        inv_a=restarted_invocations.history_by_correlation(correlation)
        audit_a=restarted_audit.history_by_correlation(correlation)
    assert inv_a==(first_invocation,) and inv_a[0] is not first_invocation
    assert audit_a==(first_audit,) and audit_a[0] is not first_audit
    assert inv_a[0].request_hash==first_invocation.request_hash and inv_a[0].response_hash==first_invocation.response_hash
    with binder.bind_tenant(_context(tenant_b,correlation)):
        inv_b=restarted_invocations.history_by_correlation(correlation)
        audit_b=restarted_audit.history_by_correlation(correlation)
    assert len(inv_b)==len(audit_b)==1 and inv_b[0].request_id==second_request.request_id
    assert restarted_invocations.history_by_correlation(correlation)==()
    assert restarted_audit.history_by_correlation(correlation)==()

    legacy=replace(first_invocation,invocation_id="inv_"+uuid4().hex*2,request_id="legacy-"+suffix,
                   correlation_id=None,output_classification=None,temperature=None,seed=None)
    codec=LLMGatewayJsonCodec()
    with owner.begin() as connection:
        connection.execute(text("INSERT INTO llm_invocations(invocation_id,request_id,prompt_version_id,provider,model_id,status,correlation_id,occurred_at,policy_version,payload,schema_version,tenant_id) VALUES(:id,:request,:prompt,:provider,:model,:status,NULL,:at,:policy,CAST(:payload AS jsonb),:schema,'legacy-internal')"),{
            "id":legacy.invocation_id,"request":legacy.request_id,"prompt":legacy.prompt_version_id,
            "provider":legacy.provider.value,"model":legacy.model_id,"status":legacy.status.value,"at":legacy.occurred_at,
            "policy":legacy.policy_version,"payload":json.dumps(codec.encode(legacy),sort_keys=True,separators=(",",":")),"schema":codec.schema_version})
    assert PostgreSQLInvocationRepository(owner).history(legacy.request_id)==(legacy,)
    assert PostgreSQLInvocationRepository(owner).history_by_correlation(correlation)==(first_invocation,inv_b[0])

    mismatch=replace(first_audit,event_id="pa_"+uuid4().hex*2,correlation_id="corr-mismatch-"+suffix)
    with binder.bind_tenant(_context(tenant_a,correlation)),pytest.raises(LLMPolicyRejected,match="mismatch"):
        PostgreSQLPromptAuditRepository(reader).append(mismatch)
    configuration_mismatch=replace(first_audit,event_id="pa_"+uuid4().hex*2,temperature=1.9)
    with binder.bind_tenant(_context(tenant_a,correlation)),pytest.raises(LLMPolicyRejected,match="configuration mismatch"):
        PostgreSQLPromptAuditRepository(reader).append(configuration_mismatch)
    with pytest.raises(DBAPIError),owner.begin() as connection:
        connection.execute(text("UPDATE llm_invocations SET correlation_id='altered' WHERE invocation_id=:id"),{"id":first_invocation.invocation_id})
    with pytest.raises(DBAPIError),owner.begin() as connection:
        connection.execute(text("DELETE FROM llm_prompt_audit WHERE event_id=:id"),{"id":first_audit.event_id})
    reader.dispose();owner.dispose()
