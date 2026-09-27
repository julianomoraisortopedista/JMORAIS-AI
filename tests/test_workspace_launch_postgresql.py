"""Mandatory PostgreSQL launch proof; runs only in an explicitly configured test DB."""
from dataclasses import replace
from uuid import uuid4
import pytest
from fastapi.encoders import jsonable_encoder
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from jmoraIs.api.app import PREFIX
from jmoraIs.api.security import CallerCredentials
from jmoraIs.api.workspace_launch import LaunchReferences, LaunchRejected, ClinicalWorkspaceLaunchService
from jmoraIs.infrastructure.workspace_launch import PostgreSQLClinicalWorkspaceLaunchRepository
from jmoraIs.infrastructure.tenant_database import create_tenant_runtime_engine
from jmoraIs.infrastructure.cryptographic_replay import PostgreSQLCryptographicReplayEngine
from jmoraIs.tenancy.context import TenantContextBinder
from tests.test_workspace_runtime_api import compose, token, remaining_data, core_persisted


@pytest.mark.parametrize('group', ['core', 'remaining'])
def test_launch_restart_bootstrap_security(core_persisted, remaining_data, group, monkeypatch):
    url, tenants, refs = core_persisted if group == 'core' else remaining_data
    runtime, canonical, logs = compose(url, tenants[0].policy_version, False, monkeypatch)
    owner = create_engine(url)
    auth, principal = token(owner, tenants[0])
    ops = canonical.operational_services
    caller = ops.authentication.authenticate(CallerCredentials(auth['authorization'][7:], 'CLINICAL_REVIEW'), uuid4().hex)
    binder = TenantContextBinder()
    raw = ({'summary': refs.clinical_state_reference, 'evidence': refs.governed_evidence_references[0],
            'explainability': refs} if group == 'core' else
           dict(zip(('timeline','medical_document','human_review','audit_defense'), refs[:4])))
    references = LaunchReferences.model_validate(jsonable_encoder(raw))
    try:
        with binder.bind(caller):
            exact = canonical.launch_producer.create(caller, references)
            first = canonical.launch_service.get_exact(caller, exact)
            assert first.references == references
            assert first.principal_id == principal.principal_id
            with pytest.raises(Exception):
                canonical.launch_service.get_exact(caller, exact.model_copy(update={'integrity_hash':'0'*64}))
            for field in ('caller_id','organization_id','tenant_id','policy_version'):
                altered=replace(caller,**{field:'other'})
                with binder.bind(altered),pytest.raises(Exception): canonical.launch_service.get_exact(altered,exact)
            name=next(iter(raw)); original=getattr(references,name)
            for field, value in [('tenant_id','other'),
                (next(key for key in original.model_dump() if key in ('reference_id','timeline_reference_id')),'forged_'+uuid4().hex)]:
                bad=original.model_copy(update={field:value})
                with pytest.raises(Exception):
                    canonical.launch_producer.create(caller,references.model_copy(update={name:bad}))
        fresh=create_tenant_runtime_engine(url,runtime_role='jmorais_application_reader')
        restarted=ClinicalWorkspaceLaunchService(PostgreSQLClinicalWorkspaceLaunchRepository(
            fresh.execution_options(postgresql_readonly=True)),ops.authorization,canonical.workspace,canonical.remaining_workspace)
        with binder.bind(caller):
            assert restarted.get_exact(caller,exact)==first
            with fresh.connect() as c:
                assert c.execute(text('SELECT rolbypassrls FROM pg_roles WHERE rolname=current_user')).scalar_one() is False
        with fresh.connect() as c:
            assert c.execute(text('SELECT count(*) FROM clinical_workspace_launches')).scalar_one()==0
        with binder.bind(replace(caller,tenant_id='other')),fresh.connect() as c:
            assert c.execute(text('SELECT count(*) FROM clinical_workspace_launches WHERE launch_id=:id'),{'id':exact.launch_id}).scalar_one()==0
        fresh.dispose()
        with TestClient(canonical.app) as client:
            body={'reference':exact.model_dump(mode='json')}
            result=client.post(PREFIX+'/workspace/bootstrap',json=body,headers=auth)
            assert result.status_code==200,result.text
            assert result.headers['cache-control']=='no-store'
            assert result.json()['references']==references.model_dump(mode='json')
            for name,value in result.json()['references'].items():
                if value is not None:
                    r=client.post(PREFIX+'/workspace/'+name.replace('_','-')+'/resolve',json={'reference':value},headers=auth)
                    assert r.status_code==200,r.text
            assert client.post(PREFIX+'/workspace/bootstrap',json=body).status_code==401
            for headers in ({**auth,'x-tenant-id':'other'},{**auth,'x-role':'ADMINISTRATOR'},{**auth,'x-purpose':'ADMINISTRATION'}):
                assert client.post(PREFIX+'/workspace/bootstrap',json=body,headers=headers).status_code in (401,403)
            for role,purposes in [('reviewer',('CLINICAL_REVIEW',)),('service',('CLINICAL_REVIEW',)),('reviewer',('INTERNAL_OPERATIONS',))]:
                other,_=token(owner,tenants[0],role=role,allowed=purposes)
                assert client.post(PREFIX+'/workspace/bootstrap',json=body,headers=other).status_code in (401,403)
            assert client.put(PREFIX+'/workspace/bootstrap',json=body,headers=auth).status_code==405
        engine=PostgreSQLCryptographicReplayEngine(owner)
        assert engine.replay_workspace_launch(exact.launch_id).integrity_status.value=='VALID'
        for statement in ('UPDATE clinical_workspace_launches SET integrity_hash=integrity_hash WHERE launch_id=:id',
                          'DELETE FROM clinical_workspace_launches WHERE launch_id=:id'):
            with pytest.raises(Exception),owner.begin() as c: c.execute(text(statement),{'id':exact.launch_id})
        # Privileged probes roll back; their replay engine shares the test transaction.
        class ConnectionEngine:
            def __init__(self,c): self.c=c; self.dialect=c.dialect
            def connect(self):
                from contextlib import nullcontext
                return nullcontext(self.c)
        for statement in ('DELETE FROM clinical_workspace_launches WHERE launch_id=:id',
                          "UPDATE clinical_workspace_launches SET payload=replace(payload,'CLINICAL_REVIEW','ADMINISTRATION') WHERE launch_id=:id",
                          "DELETE FROM cryptographic_stream_checkpoints WHERE stream_namespace='clinical_workspace_launches' AND stream_id=:id"):
            with owner.connect() as c:
                tx=c.begin()
                try:
                    c.execute(text('ALTER TABLE clinical_workspace_launches DISABLE TRIGGER USER'))
                    c.execute(text('ALTER TABLE cryptographic_stream_checkpoints DISABLE TRIGGER USER'))
                    c.execute(text(statement),{'id':exact.launch_id})
                    result=PostgreSQLCryptographicReplayEngine(ConnectionEngine(c)).replay_workspace_launch(exact.launch_id)
                    assert result.integrity_status.value=='TAMPERED'
                finally: tx.rollback()
    finally:
        canonical.database_credentials.close();owner.dispose()
