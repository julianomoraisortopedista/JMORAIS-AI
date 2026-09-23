"""Shared HTTP checks over persisted S003 owners; no replacement trust store."""
import ast
from dataclasses import asdict, replace
from pathlib import Path

import pytest
from fastapi.encoders import jsonable_encoder
from fastapi.testclient import TestClient
from sqlalchemy import event, text

from jmoraIs.api.app import ApiServices, PREFIX, create_app
from jmoraIs.api import workspace_schemas as schemas
from jmoraIs.tenancy.context import TenantContextBinder
from tests.test_internal_api import operational, headers
from tests.test_clinical_workspace_postgresql import persisted as core_persisted, compose as core_compose
from tests.test_clinical_workspace_remaining_postgresql import persisted as remaining_persisted, compose
from tests.test_clinical_workspace_remaining_postgresql import state_source

CASES = [
    ('timeline', 'timeline', schemas.TimelineRequest, schemas.TimelineResponse, 0),
    ('evidence', 'evidence', schemas.EvidenceRequest, schemas.EvidenceResponse, None),
    ('explainability', 'explainability', schemas.ExplainabilityRequest, schemas.ExplainabilityResponse, None),
    ('medical-document', 'medical_document', schemas.MedicalDocumentRequest, schemas.MedicalDocumentResponse, 1),
    ('human-review', 'human_review', schemas.HumanReviewRequest, schemas.HumanReviewResponse, 2),
    ('audit-defense', 'audit_defense', schemas.AuditDefenseRequest, schemas.AuditDefenseResponse, 3),
    ('audit-defense', 'audit_defense', schemas.AuditDefenseRequest, schemas.AuditDefenseResponse, 4),
]


@pytest.mark.parametrize('path,method,request_type,response_type,index', CASES)
def test_remaining_http_exact(path, method, request_type, response_type, index,
                              core_persisted, remaining_persisted, monkeypatch):
    if index is None:
        url, tenants, source_ref = core_persisted
        exact = source_ref.governed_evidence_references[0] if method == 'evidence' else source_ref
    else:
        url, tenants, refs = remaining_persisted
        exact = refs[index]
    reader = state_source.create_tenant_runtime_engine(url, runtime_role='jmorais_application_reader')
    reader = reader.execution_options(postgresql_readonly=True)
    statements = []
    event.listen(reader, 'before_cursor_execute', lambda c, cur, sql, p, ctx, many: statements.append(sql))
    workspace = core_compose(reader) if index is None else compose(reader)
    operations = operational()
    authentication = operations.authentication

    class AuthenticatedTenant:
        def authenticate(self, credentials, correlation_id):
            caller = authentication.authenticate(credentials, correlation_id)
            return replace(caller, tenant_id=tenants[0].tenant_id,
                           organization_id=tenants[0].organization_id,
                           policy_version=tenants[0].policy_version)

    operations = replace(operations, authentication=AuthenticatedTenant(), tenant_context=TenantContextBinder())
    kwargs = {'workspace' if index is None else 'remaining_workspace': workspace}
    endpoint = PREFIX + '/workspace/' + path + '/resolve'
    payload = {'reference': jsonable_encoder(exact)}
    assert request_type.model_validate(payload).reference.to_reference() == exact
    with TenantContextBinder().bind_tenant(tenants[0]):
        expected = response_type(**asdict(getattr(workspace, method)(exact))).model_dump(mode='json')
        with reader.connect() as c:
            assert c.execute(text('SHOW transaction_read_only')).scalar_one() == 'on'
            assert tuple(c.execute(text('SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user')).one()) == (False, False)

    def forbidden(*args, **kwargs):
        raise AssertionError('forbidden mutation/fallback')

    for owner in vars(workspace).values():
        for name in ('latest', 'history', 'at', 'reference_for', 'append'):
            monkeypatch.setattr(owner, name, forbidden, raising=False)
    try:
        with TestClient(create_app(ApiServices(), operations, **kwargs), raise_server_exceptions=False) as client:
            def post(body=payload, auth=None):
                return client.post(endpoint, json=body, headers=headers('reviewer') if auth is None else auth)
            response = post()
            assert response.status_code == 200, response.text
            assert response.json() == expected
            assert response_type.model_validate(response.json()).source_reference.to_reference() == exact
            assert response.headers['cache-control'] == 'no-store'
            if method == 'audit_defense':
                assert response.json()['state'] == exact.state.value
                assert (response.json()['stage11_document'] is None) == (index == 3)
                assert response.json()['replay_status'] == 'NOT_EVALUATED'
                assert response.json()['completeness_verified'] is None
            n = len(statements)
            assert post(auth={}).status_code == 401
            assert post(auth=headers('service')).status_code == 403
            assert post({'reference': {**payload['reference'], 'tenant_id': tenants[1].tenant_id}}).status_code == 403
            assert len(statements) == n
            for bad in ({}, {'reference': None}, {'reference': {'reference_id': 'scalar-only'}},
                        {'reference': {**payload['reference'], 'extra': 'sensitive-marker'}},
                        {'reference': {**payload['reference'], 'issued_at': 'sensitive-marker'}}):
                response = post(bad)
                assert response.status_code == 422, response.text
                assert 'sensitive-marker' not in response.text
            key = 'timeline_reference_id' if method == 'timeline' else 'reference_id'
            for field, value in ((key, 'forged-sensitive-marker'), ('integrity_hash', '0' * 64)):
                response = post({'reference': {**payload['reference'], field: value}})
                assert response.status_code == 409, response.text
                assert 'sensitive-marker' not in response.text
                assert set(response.json()) == {'code', 'message', 'correlation_id'}
            if method == 'timeline':
                bad = {**payload['reference'], 'state_references': list(reversed(payload['reference']['state_references']))}
                assert post({'reference': bad}).status_code == 409
            if method == 'audit_defense':
                bad = {**payload['reference'], 'state': 'STAGE11_LINKED' if index == 3 else 'PRE_LINK'}
                assert post({'reference': bad}).status_code == 409
            for verb in ('put', 'patch', 'delete'):
                assert getattr(client, verb)(endpoint, headers=headers('reviewer')).status_code == 405
            assert post().json() == expected
            monkeypatch.setattr(workspace, method, lambda r: (_ for _ in ()).throw(RuntimeError('password=secret SQL sensitive-marker')))
            response = post()
            assert response.status_code == 500
            assert response.json()['message'] == 'workspace request failed'
            assert response.headers['cache-control'] == 'no-store'
            assert 'sensitive-marker' not in response.text
        with TestClient(create_app(ApiServices(), replace(operations, tenant_context=None), **kwargs)) as client:
            assert client.post(endpoint, json=payload, headers=headers('reviewer')).status_code == 403
        assert 'sensitive-marker' not in str(operations.structured_log.records)
        assert getattr(exact, 'reference_id', 'timeline-reference-not-logged') not in str(operations.structured_log.records)
        assert all(sql.lstrip().split()[0].upper() in {'SELECT', 'SET', 'SHOW'} for sql in statements)
    finally:
        reader.dispose()


def test_remaining_routes_use_shared_exact_boundary():
    tree = ast.parse(Path('jmoraIs/api/app.py').read_text())
    names = {'workspace_' + case[1] for case in CASES} | {'resolve_workspace'}
    nodes = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name in names]
    assert len(nodes) == 7
    attrs = {n.attr for f in nodes for n in ast.walk(f) if isinstance(n, ast.Attribute)}
    assert 'to_reference' in attrs
    assert not attrs & {'latest', 'history', 'at', 'get', 'reference_for', 'execute', 'connect', 'begin', 'append'}
