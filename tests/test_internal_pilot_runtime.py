"""Actual uvicorn production factory + TLS + same-origin build; NON-LIVE only."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from datetime import datetime,timezone,timedelta
from uuid import uuid4
from dataclasses import replace
import ipaddress

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from fastapi.encoders import jsonable_encoder
from sqlalchemy import create_engine,text
from sqlalchemy.engine import make_url
from jmoraIs.api.security import CallerCredentials
from jmoraIs.api.workspace_launch import LaunchReferences
from jmoraIs.tenancy.context import TenantContextBinder
from jmoraIs.infrastructure.tenant_database import create_tenant_runtime_engine
from tests import test_workspace_runtime_api as runtime
from tests import test_clinical_workspace_postgresql as core
from tests import test_clinical_workspace_remaining_postgresql as remaining
from tests import test_governed_llm_draft_exact_reference_postgresql as draft


def tls_files(tmp_path):
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    now=datetime.now(timezone.utc)
    name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'localhost')])
    cert=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
          .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=1))
          .not_valid_after(now+timedelta(hours=1))
          .add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost'),x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]),critical=False)
          .sign(key,hashes.SHA256()))
    certfile=tmp_path/'fixture-cert.pem';keyfile=tmp_path/'fixture-key.pem'
    certfile.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    keyfile.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
    keyfile.chmod(0o600)
    return certfile,keyfile


def test_actual_pilot_production_runtime(tmp_path,monkeypatch):
    url=os.environ.get('JMORAIS_TEST_POSTGRES_URL','')
    if not url:pytest.skip('isolated PostgreSQL test URL required')
    assert (make_url(url).database or '').startswith('pilot_release_')
    from jmoraIs.tenancy.domain import TenantContext
    suffix=uuid4().hex
    tenants=tuple(TenantContext(prefix+suffix,prefix+'org-'+suffix,'fixture-producer',
        'INTERNAL_SERVICE','CLINICAL_VALIDATION','MIP-10.1','pilot-'+suffix)
        for prefix in ('pilot-','other-pilot-'))
    tenant=tenants[0]
    owner=create_engine(url)
    with owner.begin() as c:
        for item in tenants:
            c.execute(text("INSERT INTO tenants(tenant_id,organization_id,display_name,status,policy_version,created_at) VALUES(:t,:o,'NON-LIVE pilot fixture','ACTIVE',:p,:at)"),
                {'t':item.tenant_id,'o':item.organization_id,'p':item.policy_version,'at':datetime.now(timezone.utc)})
    owner.dispose()
    _,canonical,_=runtime.compose(url,tenant.policy_version,False,monkeypatch)
    owner=create_engine(url)
    writer=create_tenant_runtime_engine(url,runtime_role='jmorais_application_writer')
    def issue(owner,writer,suffix,tenant):
        return draft.persisted_draft(owner,writer,suffix,tenant,draft_attestor=canonical.draft_attestor)
    monkeypatch.setattr(remaining.review_source,'persisted_draft',issue)
    # The approved remaining fixture uses MIP-10.1 source policy. Do not relabel refs.
    with TenantContextBinder().bind_tenant(tenant):
        reference=core.seed(owner,writer,tenant,uuid4().hex)
        rest=remaining.seed(owner,writer,tenant,uuid4().hex)
    references=LaunchReferences.model_validate(jsonable_encoder(dict(summary=reference.clinical_state_reference,
        evidence=reference.governed_evidence_references[0],explainability=reference,timeline=rest[0],
        medical_document=rest[1],human_review=rest[2],audit_defense=rest[4])))
    auth,principal=runtime.token(owner,tenant)
    admin,_=runtime.token(owner,tenant,role='admin',allowed=('INTERNAL_OPERATIONS',))
    wrong,_=runtime.token(owner,tenant)
    wrong_tenant,_=runtime.token(owner,tenants[1])
    caller=canonical.operational_services.authentication.authenticate(
        CallerCredentials(auth['authorization'][7:],'CLINICAL_REVIEW'),uuid4().hex)
    with TenantContextBinder().bind(caller):
        exact=canonical.launch_producer.create(caller,references)
    with writer.connect() as c:
        assert tuple(c.execute(text('SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user')).one())==(False,False)
        assert c.execute(text("SELECT relrowsecurity FROM pg_class WHERE relname='clinical_workspace_launches'")).scalar_one()
    with pytest.raises(Exception),owner.begin() as c:
        c.execute(text('DELETE FROM clinical_workspace_launches WHERE launch_id=:id'),{'id':exact.launch_id})
    canonical.database_credentials.close();writer.dispose();owner.dispose()
    jwks=tmp_path/'jwks.json';jwks.write_text(json.dumps({'keys':[runtime.rt._JWK]}))
    cert,key=tls_files(tmp_path)
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    env=dict(os.environ,JMORAIS_PRODUCTION_COMPOSITION_FACTORY='tests.pilot_runtime_factory:create',
        JMORAIS_PILOT_FIXTURE_POLICY=tenant.policy_version,JMORAIS_PILOT_FIXTURE_JWKS=str(jwks),
        JMORAIS_WEB_DIST=str(Path('apps/web/dist').resolve()))
    output=tmp_path/'runtime-output.txt'
    with output.open('w') as log:
        process=subprocess.Popen([sys.executable,'-m','uvicorn','jmoraIs.api.production_asgi:create','--factory',
            '--host','127.0.0.1','--port',str(port),'--ssl-certfile',str(cert),'--ssl-keyfile',str(key),
            '--no-access-log','--no-server-header'],env=env,stdout=log,stderr=log)
        try:
            with httpx.Client(base_url=f'https://127.0.0.1:{port}',verify=str(cert),timeout=10) as client:
                for _ in range(100):
                    if process.poll() is not None:
                        from jmoraIs.infrastructure.cryptographic_replay import PostgreSQLCryptographicReplayEngine
                        diagnostic=create_engine(url)
                        with diagnostic.connect() as c:
                            audit=c.execute(text('SELECT decision,failure_category,failed_events FROM offline_replay_verifier_events')).all()
                        report=PostgreSQLCryptographicReplayEngine(diagnostic).replay_all()
                        failures=[(item.stream,tuple(f.reasons for f in item.failed_events)) for item in report.streams if item.failed_events]
                        from jmoraIs.infrastructure.offline_replay import _PinnedEngine
                        with diagnostic.connect() as c:
                            c.execute(text('SET LOCAL ROLE jmorais_offline_replay_verifier'))
                            c.execute(text('SET TRANSACTION READ ONLY'))
                            offline=PostgreSQLCryptographicReplayEngine(_PinnedEngine(c,diagnostic.dialect)).replay_all()
                        failures += [('offline:'+item.stream,tuple(f.reasons for f in item.failed_events)) for item in offline.streams if item.failed_events]
                        diagnostic.dispose()
                        pytest.fail(f'production startup replay metadata: {audit}; {failures}')
                    try:
                        if client.get('/internal/api/v1/health/live').status_code==200:break
                    except httpx.TransportError:pass
                    time.sleep(.1)
                else:pytest.fail('production process startup timed out')
                prefix='/internal/api/v1/workspace/'
                ready=client.get('/internal/api/v1/health/ready',headers={**admin,'x-purpose':'INTERNAL_OPERATIONS'})
                assert ready.status_code==200,ready.text
                assert client.get('/').status_code==200
                assert 'Clinical Workspace' in client.get('/').text
                assert client.get('/src/main.js').status_code==200
                assert client.get('/workspace-config.json').status_code==503
                assert client.get('/src/.env').status_code==404
                body={'reference':exact.model_dump(mode='json')}
                assert client.post(prefix+'bootstrap',json=body).status_code==401
                for denied in (wrong,wrong_tenant,{**auth,'x-tenant-id':'other'}):
                    assert client.post(prefix+'bootstrap',json=body,headers=denied).status_code in (401,403)
                bad={'reference':{**body['reference'],'integrity_hash':'0'*64}}
                assert client.post(prefix+'bootstrap',json=bad,headers=auth).status_code==403
                bootstrap=client.post(prefix+'bootstrap',json=body,headers=auth)
                assert bootstrap.status_code==200,bootstrap.text
                assert bootstrap.json()['references']==references.model_dump(mode='json')
                for name,ref in bootstrap.json()['references'].items():
                    assert ref is not None
                    route=prefix+name.replace('_','-')+'/resolve'
                    r=client.post(route,json={'reference':ref},headers=auth)
                    assert r.status_code==200,r.text
                    assert 'no-store' in r.headers['cache-control']
                    assert client.delete(route,headers=auth).status_code==405
                ref=bootstrap.json()['references']['summary'];ref['integrity_hash']='0'*64
                assert client.post(prefix+'summary/resolve',json={'reference':ref},headers=auth).status_code==409
        finally:
            process.terminate()
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
    logs=output.read_text()
    assert auth['authorization'][7:] not in logs and url not in logs
    assert all(line not in logs for line in key.read_text().splitlines()[1:-1])
    assert 'access_token' not in logs
