"""Focused NON-LIVE proofs for operator wrappers, without repeating release gates."""
from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace
import json
import os

import pytest
from scripts import pilot, pilot_admin
from jmoraIs.api.security import CallerContext, CallerRole, PurposeOfUse
from jmoraIs.tenancy.domain import TenantStatus


def caller():
    return CallerContext('admin', CallerRole.ADMINISTRATOR, PurposeOfUse.ADMINISTRATION,
        'correlation', 'IAM-1', organization_id='org', tenant_id='tenant', principal_type='HUMAN')


def metadata():
    return dict(provider='approved-provider', external_subject='physician-subject', principal_id='physician',
        organization_id='org', tenant_id='tenant', policy_version='IAM-1')


@pytest.mark.parametrize('change', [dict(role=CallerRole.CLINICAL_REVIEWER),
    dict(purpose=PurposeOfUse.CLINICAL_REVIEW), dict(principal_type='SERVICE'),
    dict(tenant_id='other'), dict(organization_id='other'), dict(policy_version='other')])
def test_provision_rejects_before_database(change):
    with pytest.raises(pilot.PilotRejected):
        pilot_admin.provision(object(), replace(caller(), **change), metadata())


@pytest.mark.parametrize('audit_failure', [False, True])
def test_identity_and_audit_share_transaction(monkeypatch, audit_failure):
    committed=[]
    pending=[]
    class Engine:
        @contextmanager
        def begin(self):
            try:
                yield pending
                committed.extend(pending)
            finally:
                pending.clear()
    class Repository:
        def __init__(self, engine): self.engine=engine
        def create(self, link):
            assert link.allowed_purposes==('CLINICAL_REVIEW',)
            assert link.scoped_permissions==('api:read',)
            with self.engine.begin() as connection: connection.append('link')
    class Audit:
        def __init__(self, engine): self.engine=engine
        def append(self, event):
            assert event.correlation_id=='correlation'
            with self.engine.begin() as connection:
                if audit_failure: raise RuntimeError('audit unavailable')
                connection.append('audit')
    monkeypatch.setattr(pilot_admin, 'PostgreSQLExternalIdentityLinkRepository', Repository)
    monkeypatch.setattr(pilot_admin, 'PostgreSQLIdentitySecurityAudit', Audit)
    monkeypatch.setattr(pilot_admin, 'PostgreSQLTenantRepository', lambda _:SimpleNamespace(
        get=lambda _:SimpleNamespace(status=TenantStatus.ACTIVE, organization_id='org', tenant_id='tenant', policy_version='IAM-1')))
    canonical=SimpleNamespace(database_credentials=SimpleNamespace(engine=Engine()))
    if audit_failure:
        with pytest.raises(RuntimeError): pilot_admin.provision(canonical, caller(), metadata())
        assert committed==[]
    else:
        pilot_admin.provision(canonical, caller(), metadata())
        assert committed==['link','audit']


def test_missing_configuration_fails_closed(monkeypatch):
    monkeypatch.delenv('JMORAIS_PRODUCTION_COMPOSITION_FACTORY', raising=False)
    with pytest.raises(pilot.PilotRejected, match='CONFIGURATION_REQUIRED'): pilot.Settings.load()


def test_stale_pid_never_signalled(tmp_path, monkeypatch):
    settings=SimpleNamespace(state=tmp_path, origin='https://localhost')
    path=tmp_path/'process.json'
    path.write_text(json.dumps(dict(pid=12345, origin=settings.origin, fingerprint='original')))
    path.chmod(0o600)
    monkeypatch.setattr(pilot, 'fingerprint', lambda _: 'different')
    monkeypatch.setattr(os, 'kill', lambda *_:pytest.fail('unowned process signalled'))
    with pytest.raises(pilot.PilotRejected, match='IDENTITY_CHANGED'): pilot.down(settings)
    assert path.exists()


def test_private_record_required(tmp_path):
    settings=SimpleNamespace(state=tmp_path, origin='https://localhost')
    path=tmp_path/'process.json';path.write_text('{}');path.chmod(0o644)
    with pytest.raises(pilot.PilotRejected, match='UNSAFE_PROCESS_RECORD'): pilot.read_state(settings)


def test_unattended_token_not_inferred(monkeypatch):
    monkeypatch.setattr(pilot.sys.stdin, 'isatty', lambda:False)
    with pytest.raises(pilot.PilotRejected, match='CREDENTIAL_REQUIRED'): pilot.token_input(False)


def test_launch_output_private_exclusive_external(tmp_path):
    path=tmp_path/'launch.json'
    os.close(pilot_admin.private_output(path))
    assert path.stat().st_mode & 0o777==0o600
    with pytest.raises(FileExistsError): pilot_admin.private_output(path)
    with pytest.raises(pilot.PilotRejected): pilot_admin.private_output(pilot.ROOT/'launch.json')


def test_authenticated_readiness_and_same_origin(monkeypatch):
    calls=[]
    class Client:
        def __init__(self, **kwargs):
            assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def get(self, path, **kwargs):
            calls.append((path, kwargs))
            return SimpleNamespace(status_code=200, json=lambda:dict(status='READY',checks=[
                dict(name='postgresql',ready=True),dict(name='migrations',ready=True)]))
    monkeypatch.setattr(pilot.httpx,'Client',Client)
    result=pilot.probe(SimpleNamespace(origin='https://localhost',ca_file=None),'local_test_only_bearer')
    assert all(value in ('PASS','UP') for value in result.values())
    assert calls[-1][1]['headers']['x-purpose']=='INTERNAL_OPERATIONS'
    assert all('headers' not in kwargs for _,kwargs in calls[:-1])


def test_cli_error_is_sanitized(monkeypatch, capsys):
    monkeypatch.setattr(pilot.sys,'argv',['pilot','check'])
    def reject(): raise ValueError('private diagnostic must not escape')
    monkeypatch.setattr(pilot.Settings,'load',reject)
    assert pilot.main()==1
    output=capsys.readouterr().out
    assert 'private diagnostic' not in output
    assert json.loads(output)['REASON']=='ValueError'


@pytest.mark.parametrize('healthy', [False, True])
def test_managed_startup_and_failure_cleanup(tmp_path,monkeypatch,healthy):
    process=SimpleNamespace(pid=54321,terminated=False)
    process.poll=lambda:None
    process.terminate=lambda:setattr(process,'terminated',True)
    process.wait=lambda timeout:0
    def start(command, **kwargs):
        assert command[2:5]==['uvicorn','jmoraIs.api.production_asgi:create','--factory']
        assert '--no-access-log' in command and kwargs['start_new_session']
        return process
    monkeypatch.setattr(pilot.subprocess,'Popen',start)
    monkeypatch.setattr(pilot.time,'sleep',lambda _:None)
    monkeypatch.setattr(pilot,'fingerprint',lambda _:'owned')
    monkeypatch.setattr(pilot,'probe',lambda *_:dict(READINESS='PASS' if healthy else 'FAIL'))
    settings=SimpleNamespace(state=tmp_path/'private',origin='https://localhost',port=8443,
        certificate=tmp_path/'cert',private_key=tmp_path/'key')
    if healthy:
        assert pilot.up(settings,'local_test_only_bearer')=={'READINESS':'PASS'}
        assert pilot.read_state(settings)['pid']==54321
        assert not process.terminated
    else:
        with pytest.raises(pilot.PilotRejected,match='READINESS_FAILED'):pilot.up(settings,'local_test_only_bearer')
        assert process.terminated and not pilot.state_path(settings).exists()


def test_down_only_owned_process(tmp_path,monkeypatch):
    settings=SimpleNamespace(state=tmp_path,origin='https://localhost')
    path=pilot.state_path(settings)
    path.write_text(json.dumps(dict(pid=54321,origin=settings.origin,fingerprint='owned')))
    path.chmod(0o600)
    states=iter(['owned',None])
    monkeypatch.setattr(pilot,'fingerprint',lambda _:next(states))
    signals=[]
    monkeypatch.setattr(pilot.os,'kill',lambda *args:signals.append(args))
    assert pilot.down(settings)=={'BACKEND':'STOPPED'}
    assert signals==[(54321,pilot.signal.SIGTERM)] and not path.exists()
