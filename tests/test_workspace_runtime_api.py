"""Real runtime composition and OIDC handoff; no replacement viewer/owner ports."""
from dataclasses import asdict, replace
from datetime import datetime, timezone, timedelta
import json
from uuid import uuid4

import jwt
import pytest
from fastapi.encoders import jsonable_encoder
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text

from jmoraIs.api.app import PREFIX
from jmoraIs.api.configuration import BuildMetadata, InternalApiEnvironment
from jmoraIs.api.homologation import compose_homologation
from jmoraIs.api.production import compose_production
from jmoraIs.api import production
from jmoraIs.api import workspace_schemas as schemas
from jmoraIs.clinical_workspace import ClinicalWorkspace, RemainingClinicalWorkspace
from jmoraIs.identity.domain import ExternalIdentityLink, IdentityLinkStatus, PrincipalType
from jmoraIs.infrastructure.identity_persistence import PostgreSQLExternalIdentityLinkRepository
from jmoraIs.infrastructure.secret_persistence import PostgreSQLKeyMetadataRepository
from jmoraIs.infrastructure.tenant_database import create_tenant_runtime_engine
from jmoraIs.secrets.domain import ManagedKeyMetadata, KeyState, SecretPurpose, SecretReference
from jmoraIs.tenancy.context import TenantContextBinder
from tests import test_api_homologation_postgresql as rt
from tests import test_governed_draft_signing_binding as binding
from tests import test_governed_llm_draft_exact_reference_postgresql as draft_source
from tests import test_clinical_workspace_remaining_postgresql as remaining_source
from tests.test_clinical_workspace_postgresql import persisted as core_persisted


def compose(url, policy, production_mode, monkeypatch):
    owner = create_engine(url)
    config = binding.config()
    for key in (config.pseudonymization_key, config.governed_draft_signing_key):
        PostgreSQLKeyMetadataRepository(owner).save(ManagedKeyMetadata(key, KeyState.ACTIVE,
            rt.NOW, rt.NOW, None, None, 'test-policy'))
    owner.dispose()
    config = replace(config, oidc=replace(config.oidc, policy_version=policy,
        role_mapping=(('reviewer', 'CLINICAL_REVIEWER'), ('service', 'INTERNAL_SERVICE'))))
    logs, metrics = binding.Logs(), binding.Metrics(rt.InMemoryOpenTelemetryExporter())
    kwargs = dict(metrics=metrics, structured_log=logs, identity_http_get=rt.identity_http_get,
                  secrets_provider=rt.secrets(url))
    if production_mode:
        # The existing global startup replay gate is outside this focused increment.
        monkeypatch.setattr(production.OfflineReplayVerifier, 'verify', lambda self, request: None)
        config = replace(config, environment=InternalApiEnvironment.PRODUCTION,
            build_metadata=BuildMetadata('workspace-test', 'workspace-build', 'workspace-revision', rt.NOW.isoformat()),
            offline_replay_database_credential=SecretReference('test-vault','offline-verifier',SecretPurpose.OFFLINE_REPLAY_DATABASE_CREDENTIAL,'1'))
        result = compose_production(config, **kwargs)
        return result, result.canonical, logs
    result = compose_homologation(config, **kwargs)
    return result, result, logs


@pytest.fixture
def remaining_data(monkeypatch):
    url, owner = draft_source.database()
    initial, canonical, _ = compose(url, 'MIP-10.1', False, monkeypatch)
    def issue(owner, writer, suffix, tenant):
        return draft_source.persisted_draft(owner, writer, suffix, tenant,
                                           draft_attestor=canonical.draft_attestor)
    monkeypatch.setattr(remaining_source.review_source, 'persisted_draft', issue)
    try:
        return remaining_source.persisted.__wrapped__()
    finally:
        canonical.database_credentials.close(); owner.dispose()


def token(owner, tenant, *, role='reviewer', allowed=('CLINICAL_REVIEW',)):
    now = datetime.now(timezone.utc)
    subject = uuid4().hex
    link = ExternalIdentityLink('principal-'+subject, rt.oidc().provider_id, subject,
        tenant.organization_id, tenant.tenant_id, IdentityLinkStatus.ACTIVE, PrincipalType.HUMAN,
        allowed, ('api:read',), None, now, now, tenant.policy_version)
    PostgreSQLExternalIdentityLinkRepository(owner).create(link)
    claims = dict(sub=subject, iss=rt.oidc().issuer, aud=rt.oidc().audience, iat=now, exp=now+timedelta(minutes=5),
        auth_time=int(now.timestamp()), roles=[role], organization_id=tenant.organization_id,
        sid='session-'+subject, jti='jti-'+subject)
    encoded = jwt.encode(claims, rt._KEY, algorithm='RS256', headers={'kid':'homologation-key'})
    return {'authorization': 'Bearer '+encoded}, link


@pytest.mark.parametrize('production_mode', [False, True])
@pytest.mark.parametrize('group', ['core', 'remaining'])
def test_composed_workspace_context_and_exact_http(core_persisted, remaining_data, group, production_mode, monkeypatch):
    url, tenants, references = core_persisted if group == 'core' else remaining_data
    tenant = tenants[0]
    runtime, canonical, logs = compose(url, tenant.policy_version, production_mode, monkeypatch)
    assert isinstance(canonical.workspace, ClinicalWorkspace)
    assert isinstance(canonical.remaining_workspace, RemainingClinicalWorkspace)
    owner = create_engine(url)
    auth, principal = token(owner, tenant)
    denied_role, _ = token(owner, tenant, role='service')
    denied_purpose, _ = token(owner, tenant, allowed=('INTERNAL_OPERATIONS',))
    if group == 'core':
        cases = [('summary', canonical.workspace.clinical_summary, references.clinical_state_reference, schemas.ClinicalSummaryResponse),
                 ('evidence', canonical.workspace.evidence, references.governed_evidence_references[0], schemas.EvidenceResponse),
                 ('explainability', canonical.workspace.explainability, references, schemas.ExplainabilityResponse)]
    else:
        w = canonical.remaining_workspace
        cases = [('timeline', w.timeline, references[0], schemas.TimelineResponse),
                 ('medical-document', w.medical_document, references[1], schemas.MedicalDocumentResponse),
                 ('human-review', w.human_review, references[2], schemas.HumanReviewResponse),
                 ('audit-defense', w.audit_defense, references[3], schemas.AuditDefenseResponse),
                 ('audit-defense', w.audit_defense, references[4], schemas.AuditDefenseResponse)]
    reads = []
    reader = canonical.draft_references._engine
    event.listen(reader, 'before_cursor_execute', lambda c, cur, sql, p, ctx, many: reads.append(sql))
    with TenantContextBinder().bind_tenant(tenant), reader.connect() as c:
        assert c.execute(text('SHOW transaction_read_only')).scalar_one() == 'on'
        assert tuple(c.execute(text('SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user')).one()) == (False,False)
    try:
        with TestClient(runtime.app, base_url="https://localhost", raise_server_exceptions=False) as client:
            endpoint = PREFIX+'/workspace/context'
            response = client.get(endpoint, headers=auth)
            assert response.status_code == 200, response.text
            assert response.json() == dict(caller_id=principal.principal_id, tenant_id=tenant.tenant_id,
                organization_id=tenant.organization_id, role='CLINICAL_REVIEWER', purpose='CLINICAL_REVIEW',
                permissions=['WORKSPACE_READ'])
            assert 'no-store' in {value.strip() for value in response.headers['cache-control'].split(',')}
            assert client.get(endpoint).status_code == 401
            assert client.get(endpoint,headers=denied_role).status_code == 403
            assert client.get(endpoint,headers=denied_purpose).status_code == 401
            for name in ('x-tenant-id','x-organization-id','x-role','x-authorization-state','x-purpose'):
                response=client.get(endpoint,headers={**auth,name:'caller-controlled-secret-marker'})
                assert response.status_code in (401,403)
                assert 'caller-controlled-secret-marker' not in response.text
            for name, read, reference, response_type in cases:
                with TenantContextBinder().bind_tenant(tenant):
                    expected=response_type(**asdict(read(reference))).model_dump(mode='json')
                payload={'reference':jsonable_encoder(reference)}
                route=PREFIX+'/workspace/'+name+'/resolve'
                response=client.post(route,json=payload,headers=auth)
                assert response.status_code == 200, (name,response.text)
                assert response.json()==expected
                assert response_type.model_validate(response.json()).source_reference.to_reference()==reference
                bad={'reference':{**payload['reference'],'tenant_id':tenants[1].tenant_id}}
                assert client.post(route,json=bad,headers=auth).status_code==403
            assert all(sql.lstrip().split()[0].upper() in {'SELECT','SET','SHOW'} for sql in reads)
            assert auth['authorization'] not in str(logs.records)
            assert 'caller-controlled-secret-marker' not in str(logs.records)
    finally:
        if production_mode: runtime.shutdown()
        else: canonical.database_credentials.close()
        owner.dispose()
