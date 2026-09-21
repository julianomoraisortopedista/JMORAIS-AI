import os
from dataclasses import replace
from uuid import uuid4
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine,text
from sqlalchemy.exc import DBAPIError
from jmoraIs.audit_defense import (AuditDefenseTraceabilityService,InMemoryAuditDefenseEventAdapter,
    PostgreSQLAuditDefenseEventAdapter,PostgreSQLAuditDefenseRepository,PostgreSQLMedicalDocumentTraceAdapter)
from jmoraIs.infrastructure.tenant_database import create_tenant_runtime_engine
from jmoraIs.medical_documents import DocumentType,PostgreSQLMedicalDocumentRepository
from jmoraIs.medical_documents.exact_reference_persistence import PostgreSQLMedicalDocumentExactReferenceRepository
from jmoraIs.tenancy.context import TenantContextBinder
from jmoraIs.tenancy.domain import TenantContext
from tests.test_audit_defense import NOW,setup as defense_setup
from tests.test_medical_document_engine import setup as document_setup
from evaluation.e2e_acceptance.adapters import TraceableAuditDefenseStageAdapter
from evaluation.e2e_acceptance.models import AcceptanceStage,E2ECaseIdentity,ExecutionStatus,StageExecution
pytestmark=pytest.mark.integration

def ctx(tenant,org):return TenantContext(tenant,org,"trace-service","INTERNAL_SERVICE","CLINICAL_VALIDATION","trace-policy","trace-correlation")

def test_postgresql_exact_link_restart_rls_append_only_and_tamper_detection():
    url=os.getenv("JMORAIS_TEST_POSTGRES_URL")
    if not url:pytest.skip("JMORAIS_TEST_POSTGRES_URL is required")
    config=Config("alembic.ini");config.set_main_option("sqlalchemy.url",url);command.upgrade(config,"head")
    suffix=uuid4().hex;tenant=f"trace-{suffix}";org=f"org-{suffix}";owner=create_engine(url,future=True)
    with owner.begin() as c:c.execute(text("INSERT INTO tenants(tenant_id,organization_id,display_name,status,policy_version,created_at) VALUES(:t,:o,'Trace','ACTIVE','trace-policy',:at)"),{"t":tenant,"o":org,"at":NOW})
    binder=TenantContextBinder();writer=create_tenant_runtime_engine(url,runtime_role="jmorais_application_writer")
    document=document_setup()[0].generate(document_setup()[3],DocumentType.CLINICAL_REPORT)
    document=replace(document,version_id="doc_"+uuid4().hex*2,document_stream_id="doc_"+uuid4().hex*2)
    generated=defense_setup()[0].generate(defense_setup()[3])
    generated=replace(generated,package_id="def_"+uuid4().hex*2,stream_id="def_"+uuid4().hex*2)
    with binder.bind_tenant(ctx(tenant,org)):
        documents=PostgreSQLMedicalDocumentRepository(writer);documents.append(document)
        document_reference=PostgreSQLMedicalDocumentExactReferenceRepository(writer,clock=lambda:NOW).reference_for(document)
    writer.dispose();del documents
    reader=create_tenant_runtime_engine(url,runtime_role="jmorais_application_reader");writer2=create_tenant_runtime_engine(url,runtime_role="jmorais_application_writer")
    with binder.bind_tenant(ctx(tenant,org)):
        defense_repository=PostgreSQLAuditDefenseRepository(writer2)
        trace_port=PostgreSQLMedicalDocumentTraceAdapter(PostgreSQLMedicalDocumentExactReferenceRepository(reader))
        service=AuditDefenseTraceabilityService(trace_port,defense_repository,PostgreSQLAuditDefenseEventAdapter(writer2),clock=lambda:NOW)
        def generate(_identity):defense_repository.append(generated);return defense_repository.reference_for_pre_link(generated)
        adapter=TraceableAuditDefenseStageAdapter(generate,defense_repository,trace_port,service,document_reference=document_reference)
        identity=E2ECaseIdentity("execution-"+suffix,"case-"+suffix,tenant,org,"trace-service","CLINICAL_VALIDATION","trace-correlation",("trace-policy",),NOW)
        stage11=StageExecution(AcceptanceStage.DOCUMENT,ExecutionStatus.COMPLETED,document.document_stream_id,str(document.version),(document.document.document_id,),NOW)
        linked=adapter.execute(identity,stage11);adapter.persist(linked);stage12=adapter.describe(linked);adapter.release()
        assert adapter.reread_exact(linked)==linked
        assert stage12.version=="2" and stage12.reference_id==generated.stream_id
    linked_reference=linked
    reader.dispose();writer2.dispose();del service,linked,adapter,defense_repository,trace_port
    reader2=create_tenant_runtime_engine(url,runtime_role="jmorais_application_reader")
    with binder.bind_tenant(ctx(tenant,org)):
        repo=PostgreSQLAuditDefenseRepository(reader2);reread=repo.get_exact(linked_reference)
        resolved=AuditDefenseTraceabilityService(PostgreSQLMedicalDocumentTraceAdapter(PostgreSQLMedicalDocumentExactReferenceRepository(reader2)),repo,InMemoryAuditDefenseEventAdapter(),clock=lambda:NOW).resolve_stage11_document(linked_reference)
    assert reread.stage11_document_reference.version==document.version and resolved==document
    with binder.bind_tenant(ctx("other-"+suffix,"other-org-"+suffix)):
        with pytest.raises(Exception):PostgreSQLAuditDefenseRepository(reader2).get_exact(linked_reference)
        with pytest.raises(Exception):PostgreSQLMedicalDocumentExactReferenceRepository(reader2).get_exact(document_reference)
    with pytest.raises(Exception):PostgreSQLAuditDefenseRepository(reader2).get_exact(linked_reference)
    with pytest.raises(DBAPIError),owner.begin() as c:c.execute(text("UPDATE audit_defense_versions SET stage11_document_version=99 WHERE package_id=:id"),{"id":reread.package_id})
    with pytest.raises(DBAPIError),owner.begin() as c:c.execute(text("DELETE FROM audit_defense_versions WHERE package_id=:id"),{"id":reread.package_id})
    reader2.dispose();owner.dispose()
