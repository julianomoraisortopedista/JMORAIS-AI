from dataclasses import replace
from datetime import datetime,timezone
import os
from uuid import uuid4
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine,text
from sqlalchemy.exc import DBAPIError
from jmoraIs.infrastructure.cryptographic_replay import PostgreSQLCryptographicReplayEngine,ReplayIntegrityStatus
from jmoraIs.infrastructure.tenant_database import create_tenant_runtime_engine
from jmoraIs.medical_documents import DocumentType,PostgreSQLMedicalDocumentRepository
from jmoraIs.medical_documents.exact_reference import *
from jmoraIs.medical_documents.exact_reference_persistence import PostgreSQLMedicalDocumentExactReferenceRepository
from jmoraIs.tenancy.context import TenantContextBinder
from jmoraIs.tenancy.domain import MissingTenantContext,TenantContext
from tests.test_medical_document_engine import setup

pytestmark=pytest.mark.integration
NOW=datetime(2026,9,6,tzinfo=timezone.utc)
def database():
    url=os.getenv("JMORAIS_TEST_POSTGRES_URL")
    if not url:pytest.skip("JMORAIS_TEST_POSTGRES_URL is required")
    cfg=Config("alembic.ini");cfg.set_main_option("sqlalchemy.url",url);command.upgrade(cfg,"head")
    return url,create_engine(url,future=True)
def test_owner_issuance_restart_rls_append_only_and_replay():
    url,owner=database();suffix=uuid4().hex;tenant=TenantContext("doc-ref-"+suffix,"doc-org-"+suffix,"service","INTERNAL_SERVICE","CLINICAL_VALIDATION","privacy-v1","corr-"+suffix)
    with owner.begin() as c:c.execute(text("INSERT INTO tenants(tenant_id,organization_id,display_name,status,policy_version,created_at) VALUES(:t,:o,'Document ref','ACTIVE',:p,:at)"),{"t":tenant.tenant_id,"o":tenant.organization_id,"p":tenant.policy_version,"at":NOW})
    writer=create_tenant_runtime_engine(url,runtime_role="jmorais_application_writer");binder=TenantContextBinder()
    service,_,_,inp=setup();value=service.generate(inp,DocumentType.CLINICAL_REPORT);value=replace(value,version_id="doc_"+uuid4().hex*2,document_stream_id="stream_"+uuid4().hex)
    with binder.bind_tenant(tenant):
        PostgreSQLMedicalDocumentRepository(writer).append(value);references=PostgreSQLMedicalDocumentExactReferenceRepository(writer,clock=lambda:NOW);reference=references.reference_for(value);assert references.get_exact(reference)==value
        with pytest.raises(MedicalDocumentReferenceRejected):references.get_exact(value.version_id)
    writer.dispose();del value,references
    reader=create_tenant_runtime_engine(url,runtime_role="jmorais_application_reader")
    with binder.bind_tenant(tenant):reread=PostgreSQLMedicalDocumentExactReferenceRepository(reader).get_exact(reference)
    assert reread.version_id==reference.version_id and reread.document.traceability and reread.document.provenance_references
    other=TenantContext("other-"+suffix,"other-org-"+suffix,"service","INTERNAL_SERVICE","CLINICAL_VALIDATION","privacy-v1","other-corr")
    with owner.begin() as c:c.execute(text("INSERT INTO tenants(tenant_id,organization_id,display_name,status,policy_version,created_at) VALUES(:t,:o,'Other','ACTIVE',:p,:at)"),{"t":other.tenant_id,"o":other.organization_id,"p":other.policy_version,"at":NOW})
    with binder.bind_tenant(other),pytest.raises(MedicalDocumentReferenceRejected):PostgreSQLMedicalDocumentExactReferenceRepository(reader).get_exact(reference)
    with pytest.raises(MissingTenantContext):PostgreSQLMedicalDocumentExactReferenceRepository(reader).get_exact(reference)
    for field in ({"reference_id":"mdr_"+"f"*32},{"version":2},{"predecessor":"wrong"},{"tenant_id":"wrong"},{"policy_version":"wrong"},{"document_integrity_hash":"0"*64},{"provenance_reference":"wrong"}):
        changed=replace(reference,**field,integrity_hash="0"*64);changed=replace(changed,integrity_hash=medical_document_reference_integrity(changed))
        with binder.bind_tenant(tenant),pytest.raises(MedicalDocumentReferenceRejected):PostgreSQLMedicalDocumentExactReferenceRepository(reader).get_exact(changed)
    with pytest.raises(DBAPIError),owner.begin() as c:c.execute(text("UPDATE medical_document_persisted_references SET policy_version='tampered' WHERE reference_id=:id"),{"id":reference.reference_id})
    with pytest.raises(DBAPIError),owner.begin() as c:c.execute(text("DELETE FROM medical_document_persisted_references WHERE reference_id=:id"),{"id":reference.reference_id})
    replay=PostgreSQLCryptographicReplayEngine(owner).replay_medical_document_reference(reference.reference_id,tenant_id=tenant.tenant_id);assert replay.integrity_status is ReplayIntegrityStatus.VALID
    reader.dispose();owner.dispose()
