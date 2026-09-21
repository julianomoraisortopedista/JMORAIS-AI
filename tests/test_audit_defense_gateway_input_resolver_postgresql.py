import os
from dataclasses import replace
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine,text
from sqlalchemy.exc import DBAPIError

from jmoraIs.audit_defense import (
    AuditDefenseGatewayInputIssuer,AuditDefenseGatewayInputResolver,
    AuditDefenseTraceabilityService,PostgreSQLAuditDefenseEventAdapter,
    PostgreSQLAuditDefenseRepository,PostgreSQLMedicalDocumentTraceAdapter,
)
from jmoraIs.gateway_input import HMACPersistedGatewayInputAttestor
from jmoraIs.infrastructure.managed_attestation import ManagedPersistedGatewayInputVerifier
from jmoraIs.infrastructure.managed_secrets import EphemeralSecretProvider,InMemoryKeyMetadataRepository
from jmoraIs.infrastructure.persisted_gateway_input import PostgreSQLPersistedGatewayInputRepository,PersistedGatewayInputTrustService
from jmoraIs.infrastructure.tenant_database import create_tenant_runtime_engine
from jmoraIs.medical_documents import DocumentType,PostgreSQLMedicalDocumentRepository
from jmoraIs.medical_documents.exact_reference_persistence import PostgreSQLMedicalDocumentExactReferenceRepository
from jmoraIs.secrets.domain import KeyReference,KeyState,ManagedKeyMetadata,SecretPurpose,SecretReference
from jmoraIs.tenancy.context import TenantContextBinder
from jmoraIs.tenancy.domain import TenantContext
from tests.test_audit_defense import NOW,setup as defense_setup
from tests.test_medical_document_engine import setup as document_setup

pytestmark=pytest.mark.integration
KEY=b"postgres-audit-defense-gateway-key-32bytes"


def test_restart_exact_defense_document_chain_attestation_rls_and_append_only(monkeypatch):
    url=os.getenv("JMORAIS_TEST_POSTGRES_URL")
    if not url:pytest.skip("JMORAIS_TEST_POSTGRES_URL is required")
    config=Config("alembic.ini");config.set_main_option("sqlalchemy.url",url);command.upgrade(config,"head")
    suffix=uuid4().hex;tenant=f"audit-gateway-{suffix}";org=f"org-{suffix}";owner=create_engine(url,future=True)
    current=TenantContext(tenant,org,"service","INTERNAL_SERVICE","CLINICAL_VALIDATION","policy",f"corr-{suffix}")
    other=TenantContext(f"other-{suffix}",f"other-org-{suffix}","service","INTERNAL_SERVICE","CLINICAL_VALIDATION","policy",f"other-corr-{suffix}")
    with owner.begin() as c:
        for item in (current,other):c.execute(text("INSERT INTO tenants(tenant_id,organization_id,display_name,status,policy_version,created_at) VALUES(:t,:o,'Audit Gateway','ACTIVE','policy',:at)"),{"t":item.tenant_id,"o":item.organization_id,"at":NOW})
    writer=create_tenant_runtime_engine(url,runtime_role="jmorais_application_writer");binder=TenantContextBinder()
    document=document_setup()[0].generate(document_setup()[3],DocumentType.CLINICAL_REPORT)
    document=replace(document,version_id="doc_"+uuid4().hex*2,document_stream_id="doc_"+uuid4().hex*2)
    generated=defense_setup()[0].generate(defense_setup()[3])
    generated=replace(generated,package_id="def_"+uuid4().hex*2,stream_id="def_"+uuid4().hex*2)
    key=KeyReference("memory","audit-gateway-"+suffix,"v1",SecretPurpose.SIGNING_KEY)
    secret=SecretReference("memory",key.key_id,SecretPurpose.SIGNING_KEY,"v1")
    provider=EphemeralSecretProvider({(key.key_id,"v1"):(secret,KEY)})
    metadata=InMemoryKeyMetadataRepository((ManagedKeyMetadata(key,KeyState.ACTIVE,NOW,NOW,None,None,"policy"),))
    verifier=ManagedPersistedGatewayInputVerifier(provider,metadata);attestor=HMACPersistedGatewayInputAttestor(KEY)
    with binder.bind_tenant(current):
        documents=PostgreSQLMedicalDocumentRepository(writer);documents.append(document)
        defenses=PostgreSQLAuditDefenseRepository(writer);defenses.append(generated)
        doc_owner=PostgreSQLMedicalDocumentExactReferenceRepository(writer,clock=lambda:NOW)
        trace=PostgreSQLMedicalDocumentTraceAdapter(doc_owner)
        linked_ref=AuditDefenseTraceabilityService(trace,defenses,PostgreSQLAuditDefenseEventAdapter(writer),clock=lambda:NOW).link_stage11_document(defenses.reference_for_pre_link(generated),doc_owner.reference_for(document))
        linked=defenses.get_exact(linked_ref)
        historical=defenses.history(linked.stream_id)
        assert historical[-1]==linked
        def forbidden(*args,**kwargs):raise AssertionError("historical API used for exact trust")
        with monkeypatch.context() as patch:
            patch.setattr(defenses,"history",forbidden);patch.setattr(defenses,"latest",forbidden)
            from jmoraIs.audit_defense import AuditDefenseBoundaryRejected
            for altered in (replace(linked,version=999),replace(linked,stream_id="forged"),
                            replace(linked,package_id="forged"),replace(linked,previous_package_id="forged"),
                            replace(linked,stage11_document_reference=None)):
                with pytest.raises(AuditDefenseBoundaryRejected):defenses.reference_for(altered)
            exact_reference=defenses.reference_for(linked)
            assert defenses.get_exact(exact_reference)==linked
    writer.dispose();del documents,defenses,trace,linked,generated

    issuance_reader=create_tenant_runtime_engine(url,runtime_role="jmorais_application_reader")
    input_writer=create_tenant_runtime_engine(url,runtime_role="jmorais_application_writer")
    with binder.bind_tenant(current):
        defenses=PostgreSQLAuditDefenseRepository(issuance_reader)
        trace=PostgreSQLMedicalDocumentTraceAdapter(PostgreSQLMedicalDocumentExactReferenceRepository(issuance_reader))
        reread_linked=defenses.get_exact(exact_reference)
        bound=AuditDefenseGatewayInputIssuer(defenses,attestor,clock=lambda:NOW,key_reference=key,document_trace_port=trace).issue_from_package(reread_linked,persisted_reference=exact_reference)
        record=PostgreSQLPersistedGatewayInputRepository(input_writer,verifier).append(bound)
    issuance_reader.dispose();input_writer.dispose();del defenses,trace,reread_linked,bound

    reader=create_tenant_runtime_engine(url,runtime_role="jmorais_application_reader")
    with binder.bind_tenant(current):
        restarted_records=PostgreSQLPersistedGatewayInputRepository(reader,verifier)
        restarted_defenses=PostgreSQLAuditDefenseRepository(reader)
        monkeypatch.setattr(restarted_defenses,"history",forbidden)
        monkeypatch.setattr(restarted_defenses,"latest",forbidden)
        monkeypatch.setattr(restarted_defenses,"reference_from_upstream",forbidden)
        with reader.connect() as c:
            assert c.execute(text("SHOW server_version_num")).scalar_one().startswith("16")
            role=c.execute(text("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user")).one()
            assert tuple(role)==(False,False)
        for forged in (replace(exact_reference,reference_id="forged"),replace(exact_reference,version=999),
                       replace(exact_reference,stream_id="forged"),replace(exact_reference,package_id="forged"),
                       replace(exact_reference,policy_version="forged"),replace(exact_reference,integrity_hash="0"*64)):
            with pytest.raises(AuditDefenseBoundaryRejected):restarted_defenses.get_exact(forged)
        resolver=AuditDefenseGatewayInputResolver(restarted_defenses,PostgreSQLMedicalDocumentTraceAdapter(PostgreSQLMedicalDocumentExactReferenceRepository(reader)))
        reconstructed=PersistedGatewayInputTrustService(restarted_records,verifier,{"AuditDefense":resolver}).verify_and_resolve(record.persisted_gateway_input_id)
        reread=restarted_defenses.get_exact(exact_reference)
    assert reconstructed.dto==reread.defense
    assert reread.stage11_document_reference.document_id==document.document.document_id
    assert reconstructed.reference.integrity_reference==record.upstream_artifact_reference.integrity_reference
    with binder.bind_tenant(other):
        assert PostgreSQLPersistedGatewayInputRepository(reader,verifier).get(record.persisted_gateway_input_id) is None
        with pytest.raises(Exception):PostgreSQLAuditDefenseRepository(reader).get_exact(exact_reference)
        with pytest.raises(AuditDefenseBoundaryRejected):
            PostgreSQLAuditDefenseRepository(reader).get_exact(replace(exact_reference,tenant_id=other.tenant_id))
    with pytest.raises(Exception,match="tenant context"):
        restarted_defenses.get_exact(exact_reference)
    with pytest.raises(DBAPIError),owner.begin() as c:c.execute(text("UPDATE audit_defense_versions SET status='ALTERED' WHERE stream_id=:id"),{"id":exact_reference.stream_id})
    with pytest.raises(DBAPIError),owner.begin() as c:c.execute(text("DELETE FROM audit_defense_versions WHERE stream_id=:id"),{"id":exact_reference.stream_id})
    with pytest.raises(DBAPIError),owner.begin() as c:c.execute(text("UPDATE audit_defense_persisted_references SET policy_version='ALTERED' WHERE reference_id=:id"),{"id":exact_reference.reference_id})
    reader.dispose();owner.dispose()
