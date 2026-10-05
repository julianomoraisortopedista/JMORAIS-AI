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


def _reference_checkpoint_proof(monkeypatch,*,native_only=False):
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
        trace=PostgreSQLMedicalDocumentExactReferenceRepository(writer,clock=lambda:NOW)
        pre=defenses.reference_for_pre_link(generated)
        linked_reference=AuditDefenseTraceabilityService(trace,defenses,PostgreSQLAuditDefenseEventAdapter(writer),clock=lambda:NOW).link_stage11_document(pre,trace.reference_for(document))
        linked=defenses.get_exact(linked_reference)
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
    from jmoraIs.infrastructure.cryptographic_replay import PostgreSQLCryptographicReplayEngine
    from contextlib import nullcontext
    from types import SimpleNamespace
    identifier=exact_reference.reference_id
    with owner.connect() as c:
        from hashlib import sha256
        from alembic.runtime.migration import MigrationContext
        from alembic.script import ScriptDirectory
        assert c.execute(text("SHOW server_version_num")).scalar_one().startswith("16")
        assert MigrationContext.configure(c).get_current_heads()==tuple(ScriptDirectory.from_config(config).get_heads())==("068_offline_medical_dependencies",)
        canonical_bytes=b"abc"
        expected="ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        assert c.execute(text("SELECT encode(sha256(CAST(:value AS bytea)), 'hex')"),{"value":canonical_bytes}).scalar_one()==sha256(canonical_bytes).hexdigest()==expected
        row=c.execute(text("SELECT * FROM audit_defense_persisted_references WHERE reference_id=:id"),{"id":identifier}).mappings().one()
        checkpoints=c.execute(text("SELECT stream_position,head_hash FROM cryptographic_stream_checkpoints WHERE stream_namespace='audit_defense_persisted_references' AND stream_id=:id"),{"id":identifier}).all()
        assert checkpoints==[(1,PostgreSQLCryptographicReplayEngine._audit_defense_reference_hash(row))]
        definition=c.execute(text("SELECT pg_get_functiondef('checkpoint_audit_defense_reference()'::regprocedure)")).scalar_one()
        assert 'sha256(' in definition and 'digest(' not in definition
        assert c.execute(text("SELECT count(*) FROM pg_trigger WHERE tgrelid='audit_defense_persisted_references'::regclass AND tgfoid='checkpoint_audit_defense_reference()'::regprocedure AND NOT tgisinternal AND tgenabled='O'")).scalar_one()==1
    writer.dispose()
    replay=PostgreSQLCryptographicReplayEngine(owner)
    assert replay.replay_audit_defense_reference(identifier).integrity_status=="VALID"
    owner.dispose()
    owner=create_engine(url,future=True)
    assert PostgreSQLCryptographicReplayEngine(owner).replay_audit_defense_reference(identifier).integrity_status=="VALID"
    class TransactionEngine:
        dialect=owner.dialect
        def __init__(self,connection):self.connection=connection
        def connect(self):return nullcontext(self.connection)
        def begin(self):return nullcontext(self.connection)
    mutations=(
        ("UPDATE audit_defense_persisted_references SET package_id='forged' WHERE reference_id=:id",None),
        ("UPDATE audit_defense_persisted_references SET package_version=999 WHERE reference_id=:id",None),
        ("UPDATE audit_defense_persisted_references SET tenant_id='other' WHERE reference_id=:id",None),
        ("UPDATE audit_defense_persisted_references SET stream_id='forged' WHERE reference_id=:id",None),
        ("UPDATE audit_defense_persisted_references SET reference_id='forged' WHERE reference_id=:id",None),
        ("UPDATE audit_defense_persisted_references SET policy_version='forged' WHERE reference_id=:id",None),
        ("UPDATE audit_defense_persisted_references SET integrity_hash=repeat('0',64) WHERE reference_id=:id",None),
        ("UPDATE audit_defense_persisted_references SET issued_at=issued_at+interval '1 second' WHERE reference_id=:id",None),
        ("UPDATE cryptographic_stream_checkpoints SET stream_position=2 WHERE stream_namespace='audit_defense_persisted_references' AND stream_id=:id",None),
        ("UPDATE cryptographic_stream_checkpoints SET head_hash=repeat('0',64) WHERE stream_namespace='audit_defense_persisted_references' AND stream_id=:id",None),
        ("INSERT INTO cryptographic_stream_checkpoints(stream_namespace,stream_id,stream_position,head_hash,recorded_at) SELECT stream_namespace,stream_id,2,head_hash,recorded_at FROM cryptographic_stream_checkpoints WHERE stream_namespace='audit_defense_persisted_references' AND stream_id=:id",None),
        ("DELETE FROM cryptographic_stream_checkpoints WHERE stream_namespace='audit_defense_persisted_references' AND stream_id=:id","LEGACY_MISSING_AUDIT_DEFENSE_REFERENCE_CHECKPOINT"),
        ("DELETE FROM audit_defense_persisted_references WHERE reference_id=:id","STREAM_COMPLETENESS_FAILURE"),
    )
    for sql,reason in (() if native_only else mutations):
        with owner.connect() as c:
            transaction=c.begin()
            try:
                c.execute(text("SET LOCAL session_replication_role='replica'"))
                c.execute(text(sql),{"id":identifier})
                verifier=PostgreSQLCryptographicReplayEngine(TransactionEngine(c))
                report=verifier.replay_audit_defense_reference(identifier)
                assert report.integrity_status=="TAMPERED",sql
                if reason:assert reason in repr(report)
                global_report=verifier.replay_all()
                assert global_report.integrity_status=="TAMPERED"
                assert any(x.stream=="audit_defense_persisted_references:"+identifier and x.integrity_status=="TAMPERED" for x in global_report.streams)
            finally:transaction.rollback()
    with owner.connect() as c:
        transaction=c.begin()
        try:
            repository=PostgreSQLAuditDefenseRepository(TransactionEngine(c))
            with binder.bind_tenant(current):
                c.execute(text("SELECT set_config('jmorais.tenant_id',:tenant,true)"),{"tenant":current.tenant_id})
                next_package=replace(linked,version=linked.version+1,previous_package_id=linked.package_id,package_id="def_"+uuid4().hex*2)
                repository.append(next_package)
                fixed=uuid4().hex;forced="dpr_"+fixed
                c.execute(text("INSERT INTO cryptographic_stream_checkpoints(stream_namespace,stream_id,stream_position,head_hash,recorded_at) VALUES('audit_defense_persisted_references',:id,1,repeat('0',64),:at)"),{"id":forced,"at":NOW})
                monkeypatch.setattr("jmoraIs.audit_defense.persistence.uuid4",lambda:SimpleNamespace(hex=fixed))
                with pytest.raises(DBAPIError),c.begin_nested():repository.reference_for(next_package)
                assert c.execute(text("SELECT count(*) FROM audit_defense_persisted_references WHERE reference_id=:id"),{"id":forced}).scalar_one()==0
        finally:transaction.rollback()
    with owner.connect() as c:
        transaction=c.begin()
        try:
            c.execute(text("SET LOCAL ROLE jmorais_offline_replay_verifier"))
            assert c.execute(text("SELECT reference_id FROM audit_defense_persisted_references WHERE reference_id=:id"),{"id":identifier}).scalar_one()==identifier
            assert PostgreSQLCryptographicReplayEngine(TransactionEngine(c)).replay_audit_defense_reference(identifier).integrity_status=="VALID"
        finally:transaction.rollback()
    with owner.connect() as c:
        assert tuple(c.execute(text("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname='jmorais_application_writer'")).one())==(False,False)
        assert c.execute(text("SELECT relrowsecurity FROM pg_class WHERE relname='audit_defense_persisted_references'")).scalar_one()
        for permission in ('INSERT','UPDATE','DELETE','TRUNCATE'):
            assert not c.execute(text("SELECT has_table_privilege('jmorais_offline_replay_verifier','audit_defense_persisted_references',:permission)"),{"permission":permission}).scalar_one()
    owner.dispose()


def test_reference_checkpoint_restart_tamper_deletion_and_atomicity(monkeypatch):
    _reference_checkpoint_proof(monkeypatch)


def test_native_sha256_checkpoint_insert_and_atomic_rollback(monkeypatch):
    _reference_checkpoint_proof(monkeypatch,native_only=True)


def test_corrective_migration_changes_only_hash_primitive():
    import ast
    import hashlib
    from pathlib import Path
    root=Path(__file__).parents[1]/"alembic/versions"
    historical=root/"062_audit_defense_reference_checkpoints.py"
    assert hashlib.sha256(historical.read_bytes()).hexdigest()=="598b9537b02d166085885181381b8d7c6948b990328354116e3ef6506acf7460"
    def statements(path):
        tree=ast.parse(path.read_text())
        upgrade=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=="upgrade")
        return [n.value.args[0].value for n in upgrade.body]
    old=statements(historical)[0]
    corrected=statements(root/"063_defense_checkpoint_native_sha256.py")
    expected=old.replace("CREATE FUNCTION","CREATE OR REPLACE FUNCTION",1).replace("encode(digest(","encode(sha256(",1).replace(",'sha256'),'hex')", "),'hex')",1)
    assert corrected==[expected]
