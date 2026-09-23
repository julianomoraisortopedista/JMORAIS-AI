from dataclasses import replace
import json
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from jmoraIs.api.configuration import BuildMetadata, InternalApiConfig, InternalApiEnvironment, homologation_config
from jmoraIs.api.homologation import compose_homologation, HomologationStartupError
from jmoraIs.api.production import compose_production
from jmoraIs.api.security_infrastructure import InMemoryStructuredLog, InMemoryOpenTelemetryExporter, OpenTelemetryCompatibleMetricsAdapter
from jmoraIs.governed_llm_draft.application import GovernedDraftAttestor, _integrity_hash, validate_draft_integrity
from jmoraIs.governed_llm_draft.exact_reference import GovernedLLMDraftReferenceRejected
from jmoraIs.governed_llm_draft.persistence import GovernedLLMDraftJsonCodec
from jmoraIs.infrastructure.managed_attestation import ManagedAttestationFactory, ManagedGovernedDraftVerifier
from jmoraIs.infrastructure.secret_persistence import PostgreSQLKeyMetadataRepository
from jmoraIs.secrets.domain import KeyReference, ManagedKeyMetadata, KeyState, SecretPurpose, SecretReference
from tests import test_api_homologation_postgresql as runtime
from tests import test_governed_llm_draft_exact_reference_postgresql as source


def config():
    database, pseudo = runtime.secret_refs()
    return homologation_config(database, runtime.oidc(), pseudo, governed_draft_signing_key=runtime.SIGNING_KEY)


def test_explicit_signing_configuration():
    assert config().governed_draft_signing_key == runtime.SIGNING_KEY
    for key in (None, replace(runtime.SIGNING_KEY, purpose=SecretPurpose.PSEUDONYMIZATION_HMAC)):
        with pytest.raises(ValueError):
            replace(config(), governed_draft_signing_key=key)
    with pytest.raises(ValueError):
        replace(config(), governed_draft_signing_key=replace(config().pseudonymization_key, purpose=SecretPurpose.SIGNING_KEY))
    from jmoraIs.api.configuration import development_config, test_config
    assert development_config(governed_draft_signing_key=runtime.SIGNING_KEY).governed_draft_signing_key == runtime.SIGNING_KEY
    assert test_config(governed_draft_signing_key=runtime.SIGNING_KEY).governed_draft_signing_key == runtime.SIGNING_KEY
    with pytest.raises(TypeError):
        InternalApiConfig(InternalApiEnvironment.TEST, 'localhost', None)


class Metrics(OpenTelemetryCompatibleMetricsAdapter):
    production_safe = True


class Logs(InMemoryStructuredLog):
    production_safe = True
    def flush(self): pass


def test_managed_binding_restart_compositions_and_fail_closed(monkeypatch):
    url, owner = source.database()
    provider = runtime.secrets(url)
    metadata = PostgreSQLKeyMetadataRepository(owner)
    for key in (config().pseudonymization_key, runtime.SIGNING_KEY):
        metadata.save(ManagedKeyMetadata(key, KeyState.ACTIVE, runtime.NOW, runtime.NOW, None, None, 'test-policy'))
    metrics, logs = Metrics(InMemoryOpenTelemetryExporter()), Logs()
    def compose(value):
        return compose_homologation(value, metrics=metrics, structured_log=logs,
                                   identity_http_get=runtime.identity_http_get, secrets_provider=provider)
    initial = compose(config())
    suffix = uuid4().hex
    tenant = source.TenantContext('binding-'+suffix, 'binding-org-'+suffix, 'service',
        'INTERNAL_SERVICE', 'CLINICAL_VALIDATION', 'MIP-10.1', 'corr-'+suffix)
    with owner.begin() as c:
        c.execute(text("INSERT INTO tenants(tenant_id,organization_id,display_name,status,policy_version,created_at) VALUES(:t,:o,'Binding tests','ACTIVE',:p,:at)"),
                  {'t': tenant.tenant_id, 'o': tenant.organization_id, 'p': tenant.policy_version, 'at': source.NOW})
    writer = source.create_tenant_runtime_engine(url, runtime_role='jmorais_application_writer')
    with source.TenantContextBinder().bind_tenant(tenant):
        draft, _, _, invocation = source.persisted_draft(owner, writer, suffix, tenant,
                                                        draft_attestor=initial.draft_attestor)
        invocations = source.PostgreSQLLLMInvocationExactReferenceRepository(writer)
        invocation_ref = invocations.reference_for(invocation)
        refs = source.PostgreSQLGovernedLLMDraftExactReferenceRepository(writer, initial.draft_attestor,
                                                                       invocation_references=invocations)
        reference = refs.reference_for(draft, invocation_ref)
    assert draft.signing_key_reference == runtime.SIGNING_KEY
    draft_id = draft.draft_id
    initial.database_credentials.close(); writer.dispose()
    del draft, initial, refs, invocations
    restarted = compose(config())
    with source.TenantContextBinder().bind_tenant(tenant):
        value = restarted.draft_references.get_exact(reference)
        assert value.signing_key_reference == runtime.SIGNING_KEY
        with restarted.draft_references._engine.connect() as c:
            assert c.execute(text('SHOW transaction_read_only')).scalar_one() == 'on'
            assert tuple(c.execute(text('SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user')).one()) == (False, False)
            with pytest.raises(DBAPIError):
                c.execute(text('UPDATE governed_llm_drafts SET policy_version=policy_version WHERE draft_id=:id'), {'id': draft_id})
    with pytest.raises(source.MissingTenantContext):
        restarted.draft_references.get_exact(reference)
    other = replace(tenant, tenant_id='other-'+suffix)
    with source.TenantContextBinder().bind_tenant(other), pytest.raises(GovernedLLMDraftReferenceRejected):
        restarted.draft_references.get_exact(reference)
    with owner.connect() as c:
        payload = c.execute(text('SELECT payload FROM governed_llm_drafts WHERE draft_id=:id'), {'id': draft_id}).scalar_one()
    append_writer = source.create_tenant_runtime_engine(url, runtime_role='jmorais_application_writer')
    with source.TenantContextBinder().bind_tenant(tenant):
        for statement in ('UPDATE governed_llm_drafts SET policy_version=policy_version WHERE draft_id=:id',
                          'DELETE FROM governed_llm_drafts WHERE draft_id=:id'):
            with append_writer.begin() as c:
                with pytest.raises(DBAPIError): c.execute(text(statement), {'id': draft_id})
    append_writer.dispose()
    assert payload['signing_key_reference']['__type__'] == 'KeyReference'
    assert 'draft-signing-test-key-material' not in json.dumps(payload)
    assert GovernedLLMDraftJsonCodec().decode(payload).signing_key_reference == runtime.SIGNING_KEY
    factory = ManagedAttestationFactory(provider, metadata)
    for wrong in (replace(runtime.SIGNING_KEY, key_id='wrong'), replace(runtime.SIGNING_KEY, version='wrong')):
        with pytest.raises(HomologationStartupError, match='signing key unavailable'):
            compose(replace(config(), governed_draft_signing_key=wrong))
        assert not ManagedGovernedDraftVerifier(factory, wrong, actor_id='test').verify(value)
    assert not factory.draft_attestor(runtime.SIGNING_KEY, actor_id='test').verify(
        replace(value, signing_key_reference=replace(runtime.SIGNING_KEY, version='wrong')))
    # Wrong bytes under the authorized identity are not sufficient for verification.
    assert not GovernedDraftAttestor(b'wrong-key-material-at-least-32-bytes', key_reference=runtime.SIGNING_KEY).verify(value)
    with monkeypatch.context() as patch:
        use_secret = provider.use_secret
        def unavailable(reference, **kwargs):
            if reference.purpose is SecretPurpose.SIGNING_KEY:
                raise RuntimeError('secret-value-must-not-leak')
            return use_secret(reference, **kwargs)
        patch.setattr(provider, 'use_secret', unavailable)
        with pytest.raises(HomologationStartupError, match='signing key unavailable') as error:
            compose(config())
        assert 'secret-value' not in str(error.value)
        with source.TenantContextBinder().bind_tenant(tenant), pytest.raises(GovernedLLMDraftReferenceRejected):
            restarted.draft_references.get_exact(reference)
    # Privileged tampering is confined to rolled-back test transactions.
    class BoundEngine:
        dialect = owner.dialect
        def __init__(self, connection): self.connection = connection
        def connect(self):
            from contextlib import nullcontext
            return nullcontext(self.connection)
    for legacy in (False, True):
        with owner.connect() as c:
            transaction = c.begin()
            c.execute(text('SET LOCAL session_replication_role=replica'))
            damaged = json.loads(json.dumps(payload))
            if legacy:
                legacy_value = replace(value, signing_key_reference=None)
                legacy_value = replace(legacy_value, integrity_hash=_integrity_hash(legacy_value))
                legacy_attestor = GovernedDraftAttestor(b'draft-signing-test-key-material-32-bytes')
                legacy_value = replace(legacy_value, issuance_attestation=legacy_attestor.sign(legacy_value))
                assert validate_draft_integrity(legacy_value, legacy_attestor)
                damaged = GovernedLLMDraftJsonCodec().encode(legacy_value)
                damaged.pop('signing_key_reference')
            else:
                damaged['signing_key_reference']['version'] = 'tampered-version'
            c.execute(text('UPDATE governed_llm_drafts SET payload=CAST(:p AS jsonb) WHERE draft_id=:id'),
                      {'p': json.dumps(damaged), 'id': draft_id})
            with source.TenantContextBinder().bind_tenant(tenant):
                with monkeypatch.context() as patch:
                    patch.setattr(restarted.draft_references, '_engine', BoundEngine(c))
                    with pytest.raises(GovernedLLMDraftReferenceRejected) as error:
                        restarted.draft_references.get_exact(reference)
                    if legacy: assert 'LEGACY_MISSING_GOVERNED_DRAFT_SIGNING_KEY' in str(error.value)
            transaction.rollback()
    # Production invokes the same real composition; the previously approved global
    # startup replay gate is isolated here to obey the focused/no-replay test scope.
    from jmoraIs.api import production
    monkeypatch.setattr(production.OfflineReplayVerifier, 'verify', lambda self, request: None)
    production_config = replace(config(), environment=InternalApiEnvironment.PRODUCTION,
        build_metadata=BuildMetadata('binding-test', 'binding-build', 'binding-revision', source.NOW.isoformat()),
        offline_replay_database_credential=SecretReference('test-vault','offline-verifier',SecretPurpose.OFFLINE_REPLAY_DATABASE_CREDENTIAL,'1'))
    production_runtime = compose_production(production_config, metrics=metrics, structured_log=logs,
        identity_http_get=runtime.identity_http_get, secrets_provider=provider)
    with source.TenantContextBinder().bind_tenant(tenant):
        assert production_runtime.canonical.draft_references.get_exact(reference) == value
    assert 'draft-signing-test-key-material' not in str(logs.records)
    production_runtime.shutdown(); restarted.database_credentials.close(); owner.dispose()
