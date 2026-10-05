"""S003 exact state transition, restart, RLS and state-tamper proof."""
from contextlib import nullcontext
from dataclasses import replace
from datetime import timedelta
import os
import json
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from jmoraIs.audit_defense import (
    AuditDefenseBoundaryRejected, AuditDefenseTraceabilityService, AuditDefenseVersionConflict,
    DefenseReferenceState, LegacyDefenseReference, PostgreSQLAuditDefenseRepository,
    PostgreSQLAuditDefenseEventAdapter, PersistedDefensePackageReference,
)
from jmoraIs.infrastructure.cryptographic_replay import PostgreSQLCryptographicReplayEngine
from jmoraIs.infrastructure.tenant_database import create_tenant_runtime_engine
from jmoraIs.medical_documents import PostgreSQLMedicalDocumentRepository
from jmoraIs.medical_documents.exact_reference_persistence import PostgreSQLMedicalDocumentExactReferenceRepository
from jmoraIs.medical_documents.exact_reference import MedicalDocumentReferenceRejected, medical_document_reference_integrity
from jmoraIs.audit_defense.persistence import AuditDefenseJsonCodec
from jmoraIs.tenancy.context import TenantContextBinder
from jmoraIs.tenancy.domain import MissingTenantContext
from tests.test_audit_defense import NOW, setup as defense_setup
from tests.test_audit_defense_reference_states import context, document_value

pytestmark=pytest.mark.integration


def test_pre_link_stage11_transition_restart_rls_and_state_tamper(monkeypatch):
    url=os.getenv("JMORAIS_TEST_POSTGRES_URL")
    if not url:pytest.skip("JMORAIS_TEST_POSTGRES_URL is required")
    owner=create_engine(url,future=True)
    cfg=Config("alembic.ini");cfg.set_main_option("sqlalchemy.url",url)
    # Existing references/checkpoints remain byte-for-byte unchanged by the migration.
    with owner.connect() as c:
        before=c.execute(text("SELECT reference_id,integrity_hash,issued_at FROM audit_defense_persisted_references ORDER BY sequence_id")).all()
        anchors_before=c.execute(text("SELECT * FROM cryptographic_stream_checkpoints WHERE stream_namespace='audit_defense_persisted_references' ORDER BY checkpoint_id")).all()
    command.upgrade(cfg,"head")
    with owner.connect() as c:
        assert c.execute(text("SHOW server_version_num")).scalar_one().startswith("16")
        assert MigrationContext.configure(c).get_current_heads()==tuple(ScriptDirectory.from_config(cfg).get_heads())==("068_offline_medical_dependencies",)
        assert before==c.execute(text("SELECT reference_id,integrity_hash,issued_at FROM audit_defense_persisted_references ORDER BY sequence_id")).all()
        assert anchors_before==c.execute(text("SELECT * FROM cryptographic_stream_checkpoints WHERE stream_namespace='audit_defense_persisted_references' ORDER BY checkpoint_id")).all()
    suffix=uuid4().hex
    tenant=context("state-"+suffix);other=context("other-"+suffix);binder=TenantContextBinder()
    with owner.begin() as c:
        for t in (tenant,other):
            c.execute(text("INSERT INTO tenants(tenant_id,organization_id,display_name,status,policy_version,created_at) VALUES(:t,:o,'Reference states','ACTIVE','policy',:at)"),{"t":t.tenant_id,"o":t.organization_id,"at":NOW})
    writer=create_tenant_runtime_engine(url,runtime_role="jmorais_application_writer")
    with binder.bind_tenant(tenant):
        service,_,_,inp=defense_setup();original=service.generate(inp)
        original=replace(original,package_id="def_"+uuid4().hex*2,stream_id="def_"+uuid4().hex*2)
        original_defense=original.defense
        repo=PostgreSQLAuditDefenseRepository(writer);repo.append(original)
        pre=repo.reference_for_pre_link(original)
        assert pre.state is DefenseReferenceState.PRE_LINK and repo.get_exact(pre)==original
        for bad in (replace(original,package_id="forged"),replace(original,version=999),replace(original,previous_package_id="forged")):
            with pytest.raises(AuditDefenseBoundaryRejected):repo.reference_for_pre_link(bad)
        doc=replace(document_value(),version_id="doc_"+uuid4().hex*2,document_stream_id="doc_"+uuid4().hex*2)
        PostgreSQLMedicalDocumentRepository(writer).append(doc)
        doc_owner=PostgreSQLMedicalDocumentExactReferenceRepository(writer,clock=lambda:NOW)
        doc_ref=doc_owner.reference_for(doc)
        assert doc_owner.get_exact(doc_ref)==doc
    writer.dispose();del repo,writer,original,service,doc_owner,doc
    # Fresh runtime must prove PRE_LINK from storage with no retained package object.
    writer=create_tenant_runtime_engine(url,runtime_role="jmorais_application_writer")
    repo=PostgreSQLAuditDefenseRepository(writer)
    documents=PostgreSQLMedicalDocumentExactReferenceRepository(writer)
    trace=AuditDefenseTraceabilityService(documents,repo,PostgreSQLAuditDefenseEventAdapter(writer),clock=lambda:NOW+timedelta(seconds=1))
    def forbidden(*args,**kwargs):raise AssertionError("historical trust lookup")
    monkeypatch.setattr(repo,"latest",forbidden);monkeypatch.setattr(repo,"history",forbidden)
    with binder.bind_tenant(tenant):
        assert repo.get_exact(pre).stage11_document_reference is None
        assert repo.get_exact(pre).package_id==pre.package_id
        with pytest.raises(AuditDefenseBoundaryRejected):trace.link_stage11_document(pre.stream_id,doc_ref)
        with pytest.raises(Exception):trace.link_stage11_document(pre,replace(doc_ref,reference_id="forged"))
        linked=trace.link_stage11_document(pre,doc_ref)
        assert linked.state is DefenseReferenceState.STAGE11_LINKED
        assert repo.reference_for(repo.get_exact(linked))==linked
        with pytest.raises(AuditDefenseBoundaryRejected):repo.append(replace(repo.get_exact(linked),package_id="downgrade-"+suffix,version=linked.version+1,previous_package_id=linked.package_id,stage11_document_reference=None))
        assert repo.get_exact(pre).stage11_document_reference is None
        with pytest.raises(AuditDefenseVersionConflict):trace.link_stage11_document(pre,doc_ref)
        with pytest.raises(AuditDefenseBoundaryRejected):trace.link_stage11_document(linked,doc_ref)
        with pytest.raises(AuditDefenseBoundaryRejected):repo.reference_for_pre_link(repo.get_exact(linked))
        for reference in (pre,linked):
            opposite=DefenseReferenceState.STAGE11_LINKED if reference.state is DefenseReferenceState.PRE_LINK else DefenseReferenceState.PRE_LINK
            for bad in (replace(reference,state=opposite),replace(reference,state=None),replace(reference,policy_version="forged"),replace(reference,integrity_hash="0"*64)):
                with pytest.raises(AuditDefenseBoundaryRejected):repo.get_exact(bad)
    writer.dispose();del repo,documents,trace,writer
    reader=create_tenant_runtime_engine(url,runtime_role="jmorais_application_reader")
    repo=PostgreSQLAuditDefenseRepository(reader);documents=PostgreSQLMedicalDocumentExactReferenceRepository(reader)
    trace=AuditDefenseTraceabilityService(documents,repo,PostgreSQLAuditDefenseEventAdapter(reader),clock=lambda:NOW)
    with binder.bind_tenant(tenant):
        value=repo.get_exact(linked)
        assert value.defense==original_defense and value.previous_package_id==pre.package_id
        assert value.version==pre.version+1 and value.stage11_document_reference==doc_ref
        assert trace.resolve_stage11_document(linked)==documents.get_exact(doc_ref)
        assert repo.get_exact(pre).stage11_document_reference is None
    with binder.bind_tenant(other):
        with pytest.raises(AuditDefenseBoundaryRejected):trace.resolve_stage11_document(linked)
        with pytest.raises(MedicalDocumentReferenceRejected):documents.get_exact(doc_ref)
        for reference in (pre,linked):
            with pytest.raises(AuditDefenseBoundaryRejected):repo.get_exact(reference)
        with reader.connect() as c:
            assert c.execute(text("SELECT count(*) FROM audit_defense_persisted_references WHERE reference_id IN (:a,:b)"),{"a":pre.reference_id,"b":linked.reference_id}).scalar_one()==0
            assert c.execute(text("SELECT count(*) FROM medical_document_persisted_references WHERE reference_id=:id"),{"id":doc_ref.reference_id}).scalar_one()==0
            assert c.execute(text("SELECT count(*) FROM medical_document_versions WHERE version_id=:id"),{"id":doc_ref.version_id}).scalar_one()==0
    with pytest.raises(MissingTenantContext):trace.resolve_stage11_document(linked)
    with pytest.raises(MissingTenantContext):documents.get_exact(doc_ref)
    for reference in (pre,linked):
        with pytest.raises(MissingTenantContext):repo.get_exact(reference)
    class TransactionEngine:
        dialect=owner.dialect
        def __init__(self,c):self.c=c
        def connect(self):return nullcontext(self.c)
    # Link columns and the complete persisted reference are both authenticated.
    # Even a self-consistent forged reference cannot replace the owner-issued link.
    forged=replace(doc_ref,reference_id="forged-"+suffix)
    forged=replace(forged,integrity_hash=medical_document_reference_integrity(forged))
    forged_package=replace(value,stage11_document_reference=forged)
    for tamper in ("link-column","complete-reference"):
        with owner.connect() as c:
            tx=c.begin()
            try:
                c.execute(text("SET LOCAL session_replication_role='replica'"))
                if tamper=="link-column":
                    c.execute(text("UPDATE audit_defense_versions SET stage11_document_id='forged' WHERE package_id=:id"),{"id":linked.package_id})
                else:
                    c.execute(text("UPDATE audit_defense_versions SET payload=CAST(:payload AS jsonb),stage11_document_integrity_hash=:hash WHERE package_id=:id"),
                        {"id":linked.package_id,"hash":forged.integrity_hash,"payload":json.dumps(AuditDefenseJsonCodec().encode(forged_package))})
                bound=TransactionEngine(c)
                exact=AuditDefenseTraceabilityService(documents,PostgreSQLAuditDefenseRepository(bound),None,clock=lambda:NOW)
                with binder.bind_tenant(tenant),pytest.raises(AuditDefenseBoundaryRejected):exact.resolve_stage11_document(linked)
                c.execute(text("SET LOCAL ROLE jmorais_offline_replay_verifier"))
                report=PostgreSQLCryptographicReplayEngine(bound).replay_audit_defense_reference(linked.reference_id)
                # Reference-row completeness can remain true when its linked payload is tampered.
                assert report.integrity_status=="TAMPERED"
            finally:tx.rollback()
    with binder.bind_tenant(tenant):
        assert trace.resolve_stage11_document(linked)==documents.get_exact(doc_ref)
    for reference in (pre,linked):
        with owner.connect() as c:
            tx=c.begin()
            c.execute(text("SET TRANSACTION READ ONLY"))
            row=c.execute(text("SELECT * FROM audit_defense_persisted_references WHERE reference_id=:id"),{"id":reference.reference_id}).mappings().one()
            cp=c.execute(text("SELECT stream_position,head_hash FROM cryptographic_stream_checkpoints WHERE stream_namespace='audit_defense_persisted_references' AND stream_id=:id"),{"id":reference.reference_id}).one()
            assert tuple(cp)==(1,PostgreSQLCryptographicReplayEngine._audit_defense_reference_hash(row))
            assert row["reference_state"]==reference.state.value
            assert PostgreSQLCryptographicReplayEngine(TransactionEngine(c)).replay_audit_defense_reference(reference.reference_id).integrity_status=="VALID"
            c.execute(text("SET LOCAL ROLE jmorais_offline_replay_verifier"))
            assert c.execute(text("SHOW transaction_read_only")).scalar_one()=="on"
            report=PostgreSQLCryptographicReplayEngine(TransactionEngine(c)).replay_audit_defense_reference(reference.reference_id)
            assert report.integrity_status=="VALID" and report.completeness_verified
            tx.rollback()
        with pytest.raises(DBAPIError),owner.begin() as c:
            c.execute(text("UPDATE audit_defense_persisted_references SET reference_state='PRE_LINK' WHERE reference_id=:id"),{"id":reference.reference_id})
        for tamper in ("PRE_LINK" if reference.state is DefenseReferenceState.STAGE11_LINKED else "STAGE11_LINKED",None):
            with owner.connect() as c:
                tx=c.begin()
                try:
                    c.execute(text("SET LOCAL session_replication_role='replica'"))
                    c.execute(text("UPDATE audit_defense_persisted_references SET reference_state=:state WHERE reference_id=:id"),{"state":tamper,"id":reference.reference_id})
                    c.execute(text("SET LOCAL ROLE jmorais_offline_replay_verifier"))
                    report=PostgreSQLCryptographicReplayEngine(TransactionEngine(c)).replay_audit_defense_reference(reference.reference_id)
                    assert report.integrity_status=="TAMPERED" and not report.completeness_verified
                finally:tx.rollback()
    with owner.connect() as c:
        for role in ("jmorais_application_writer","jmorais_application_reader"):
            assert tuple(c.execute(text("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=:r"),{"r":role}).one())==(False,False)
        for table in ("audit_defense_versions","audit_defense_persisted_references"):
            assert c.execute(text("SELECT relrowsecurity FROM pg_class WHERE oid=CAST(:t AS regclass)"),{"t":table}).scalar_one()
            for permission in ("INSERT","UPDATE","DELETE","TRUNCATE"):
                assert not c.execute(text("SELECT has_table_privilege('jmorais_offline_replay_verifier',:t,:p)"),{"t":table,"p":permission}).scalar_one()
        # Pre-existing NULL rows are explicitly legacy, never state-inferred.
        legacy=c.execute(text("SELECT * FROM audit_defense_persisted_references WHERE reference_state IS NULL LIMIT 1")).mappings().first()
    if legacy:
        r=PersistedDefensePackageReference(legacy["reference_id"],legacy["stream_id"],legacy["package_version"],legacy["package_id"],legacy["tenant_id"],legacy["policy_version"],legacy["integrity_hash"],legacy["issued_at"])
        with binder.bind_tenant(context(legacy["tenant_id"])),pytest.raises(LegacyDefenseReference):repo.get_exact(r)
    reader.dispose();owner.dispose()
