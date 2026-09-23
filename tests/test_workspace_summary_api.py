"""Focused S004 HTTP boundary proof with the approved persisted Workspace fixture."""
import ast
from dataclasses import asdict, replace
from pathlib import Path

import pytest
from fastapi.encoders import jsonable_encoder
from fastapi.testclient import TestClient

from jmoraIs.api.app import ApiServices, PREFIX, create_app
from jmoraIs.api.workspace_schemas import ClinicalSummaryRequest, ClinicalSummaryResponse
from jmoraIs.tenancy.context import TenantContextBinder
from tests.test_internal_api import operational, headers
from tests.test_clinical_workspace_postgresql import persisted, runtime

URL = PREFIX + "/workspace/summary/resolve"


def test_exact_summary_http_boundary(runtime, monkeypatch):
    reader, workspace, tenants, reference = runtime
    exact = reference.clinical_state_reference
    operations = operational()
    authentication = operations.authentication

    class AuthenticatedTenant:
        def authenticate(self, credentials, correlation_id):
            caller = authentication.authenticate(credentials, correlation_id)
            return replace(caller, tenant_id=tenants[0].tenant_id,
                           organization_id=tenants[0].organization_id,
                           policy_version=tenants[0].policy_version)

    operations = replace(operations, authentication=AuthenticatedTenant(), tenant_context=TenantContextBinder())
    calls = []
    get_exact = workspace._states.get_exact

    def exact_read(value):
        calls.append(value)
        return get_exact(value)

    def forbidden(*args, **kwargs):
        raise AssertionError("forbidden fallback or mutation")

    monkeypatch.setattr(workspace._states, "get_exact", exact_read)
    for name in ("latest", "history", "at", "reference_for", "append"):
        monkeypatch.setattr(workspace._states, name, forbidden, raising=False)
    payload = {"reference": jsonable_encoder(exact)}
    assert ClinicalSummaryRequest.model_validate(payload).reference.to_reference() == exact
    with TenantContextBinder().bind_tenant(tenants[0]):
        expected = ClinicalSummaryResponse(**asdict(workspace.clinical_summary(exact))).model_dump(mode="json")
    app = create_app(ApiServices(), operations, workspace=workspace)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(URL, json=payload, headers=headers('reviewer'))
        assert response.status_code == 200, response.text
        assert response.json() == expected
        assert ClinicalSummaryResponse.model_validate(response.json()).source_reference.to_reference() == exact
        assert response.headers['cache-control'] == 'no-store'
        assert calls[-1] == exact
        count = len(calls)
        assert client.post(URL, json=payload).status_code == 401
        assert client.post(URL, json=payload, headers=headers('service')).status_code == 403
        invalid_auth = {**headers('reviewer'), 'authorization': 'Bearer invalid-sensitive-token'}
        assert client.post(URL, json=payload, headers=invalid_auth).status_code == 401
        cross = {'reference': {**payload['reference'], 'tenant_id': tenants[1].tenant_id}}
        assert client.post(URL, json=cross, headers=headers('reviewer')).status_code == 403
        assert len(calls) == count
        for body in ({}, {'reference': None}, {'reference': {'state_id': exact.state_id}},
                     {'reference': {**payload['reference'], 'extra': 'sensitive-value'}},
                     {'reference': {**payload['reference'], 'issued_at': 'sensitive-value'}},
                     {'reference': {**payload['reference'], 'state_version': True}}):
            result = client.post(URL, json=body, headers=headers('reviewer'))
            assert result.status_code == 422, result.text
            assert 'sensitive-value' not in result.text
            assert set(result.json()) == {'code', 'message', 'correlation_id'}
        for key, value in [('reference_id', 'fabricated'), ('state_id', 'wrong-state'),
                           ('policy_version', 'wrong-policy'), ('integrity_hash', '0' * 64)]:
            result = client.post(URL, json={'reference': {**payload['reference'], key: value}},
                                 headers=headers('reviewer'))
            assert result.status_code == 409, result.text
            assert exact.state_id not in result.text
        for method in ('put', 'patch', 'delete'):
            assert getattr(client, method)(URL, headers=headers('reviewer')).status_code == 405
        assert client.post(URL, json=payload, headers=headers('reviewer')).json() == expected
        monkeypatch.setattr(workspace._states, 'get_exact', lambda r: (_ for _ in ()).throw(
            RuntimeError('password=secret SQL clinical-sensitive-value')))
        result = client.post(URL, json=payload, headers=headers('reviewer'))
        assert result.status_code == 500
        assert result.json()['message'] == 'workspace request failed'
        assert result.headers['cache-control'] == 'no-store'
        assert 'secret' not in result.text and 'SQL' not in result.text
    safe_logs = str(operations.structured_log.records)
    assert exact.reference_id not in safe_logs and 'clinical-sensitive-value' not in safe_logs
    without_context = create_app(ApiServices(), replace(operations, tenant_context=None), workspace=workspace)
    with TestClient(without_context) as client:
        assert client.post(URL, json=payload, headers=headers('reviewer')).status_code == 403
    # The inherited fixture verifies every DB statement is SELECT/SET/SHOW.
    from sqlalchemy import text
    with TenantContextBinder().bind_tenant(tenants[0]), reader.connect() as connection:
        assert connection.execute(text('SHOW transaction_read_only')).scalar_one() == 'on'
        assert tuple(connection.execute(text('SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user')).one()) == (False, False)


def test_summary_route_trust_path():
    tree = ast.parse(Path('jmoraIs/api/app.py').read_text())
    route = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == 'clinical_summary')
    attributes = {node.attr for node in ast.walk(route) if isinstance(node, ast.Attribute)}
    assert 'clinical_summary' in attributes and 'to_reference' in attributes
    assert not attributes.intersection({'latest', 'history', 'at', 'execute', 'connect', 'begin', 'get', 'reference_for', 'append'})
    transport = ast.parse(Path('jmoraIs/api/workspace_schemas.py').read_text())
    assert not any(isinstance(node, ast.Attribute) and node.attr in {'reference_for', 'latest', 'history', 'at'}
                   for node in ast.walk(transport))
