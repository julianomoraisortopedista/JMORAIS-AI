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


def test_pgi_defense_exact_reference_link_restart_integrity_rls(monkeypatch):
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
    with binder.bind_tenant(current):
        issuer=AuditDefenseGatewayInputIssuer(defenses,attestor,clock=lambda:NOW,key_reference=key,document_trace_port=trace)
        bound=issuer.issue_from_package(linked,persisted_reference=exact_reference)
        records=PostgreSQLPersistedGatewayInputRepository(writer,verifier)
        from jmoraIs.gateway_input import PersistedGatewayInputError,persisted_gateway_input_integrity_hash
        for reference in (None,replace(exact_reference,reference_id="forged"),
                          replace(exact_reference,package_id="forged"),replace(exact_reference,version=999),
                          replace(exact_reference,tenant_id=other.tenant_id),replace(exact_reference,policy_version="forged"),
                          replace(exact_reference,integrity_hash="0"*64)):
            with pytest.raises((PersistedGatewayInputError,AuditDefenseBoundaryRejected)):
                records.append(replace(bound,audit_defense_reference=reference))
        record=records.append(bound)
        assert record.audit_defense_reference is exact_reference
        identifier=record.persisted_gateway_input_id
        expected_reference_id=exact_reference.reference_id
        expected_package_id=exact_reference.package_id
        for field,value in (("reference_id","forged"),("package_id","forged"),("version",999),
                            ("tenant_id","forged"),("policy_version","forged"),("integrity_hash","0"*64)):
            altered=replace(record,audit_defense_reference=replace(exact_reference,**{field:value}))
            assert persisted_gateway_input_integrity_hash(altered)!=record.integrity_hash
    writer.dispose()
    del documents,defenses,trace,linked,generated,exact_reference,issuer,records,bound,record,reference,altered
    reader=create_tenant_runtime_engine(url,runtime_role="jmorais_application_reader")
    with binder.bind_tenant(current):
        records=PostgreSQLPersistedGatewayInputRepository(reader,verifier)
        record=records.get(identifier)
        assert record.audit_defense_linkage_status=="EXACT"
        assert record.audit_defense_reference.reference_id==expected_reference_id
        defenses=PostgreSQLAuditDefenseRepository(reader)
        monkeypatch.setattr(defenses,"history",forbidden)
        monkeypatch.setattr(defenses,"latest",forbidden)
        monkeypatch.setattr(defenses,"reference_from_upstream",forbidden)
        package=defenses.get_exact(record.audit_defense_reference)
        assert package.package_id==expected_package_id
        from jmoraIs.gateway_input import PersistedGatewayInput,canonical_dto_hash
        assert canonical_dto_hash(package.defense)==record.dto_hash
        assert verifier.verify(PersistedGatewayInput(package.defense,record.upstream_artifact_reference,record.dto_hash,record.issued_at,record.attestation,record.attestation_key_reference,record.audit_defense_reference))
        with reader.connect() as c:
            assert c.execute(text("SHOW server_version_num")).scalar_one().startswith("16")
            assert tuple(c.execute(text("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user")).one())==(False,False)
            row=c.execute(text("SELECT * FROM persisted_gateway_inputs WHERE persisted_gateway_input_id=:id"),{"id":identifier}).mappings().one()
        from copy import deepcopy
        corrupted=dict(row);corrupted["payload"]=deepcopy(row["payload"])
        corrupted["payload"]["audit_defense_reference"]["package_id"]="forged"
        with pytest.raises(PersistedGatewayInputError):records._checked(corrupted)
        corrupted=dict(row);corrupted["audit_defense_reference_id"]="forged"
        with pytest.raises(PersistedGatewayInputError):records._checked(corrupted)
    with binder.bind_tenant(other):
        assert records.get(identifier) is None
    with pytest.raises(Exception,match="tenant context"):records.get(identifier)
    from jmoraIs.infrastructure.cryptographic_replay import PostgreSQLCryptographicReplayEngine
    report=PostgreSQLCryptographicReplayEngine(owner).replay_persisted_gateway_input(identifier,tenant_id=current.tenant_id)
    assert report.integrity_status=="VALID"
    with pytest.raises(DBAPIError),owner.begin() as c:
        c.execute(text("UPDATE persisted_gateway_inputs SET audit_defense_reference_id=NULL WHERE persisted_gateway_input_id=:id"),{"id":identifier})
    with pytest.raises(DBAPIError),owner.begin() as c:
        c.execute(text("DELETE FROM persisted_gateway_inputs WHERE persisted_gateway_input_id=:id"),{"id":identifier})
    reader.dispose();owner.dispose()
