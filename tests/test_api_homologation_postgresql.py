from __future__ import annotations

import os
from uuid import uuid4
from datetime import datetime, timezone

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from jmoraIs.api.configuration import homologation_config
from jmoraIs.api.homologation import HomologationStartupError, compose_homologation, startup_self_check
from jmoraIs.api.security import ApiAccessAuditEvent, CallerRole, PurposeOfUse, ReadinessCheck, ReadinessReport
from jmoraIs.api.security_infrastructure import (
    DeterministicDevelopmentAuthenticator, DevelopmentIdentity, InMemoryOpenTelemetryExporter,
    InMemoryStructuredLog, OpenTelemetryCompatibleMetricsAdapter,
)
from jmoraIs.infrastructure.api_operational_audit import PostgreSQLApiAccessAuditAdapter
from jmoraIs.identity.configuration import OIDCProviderConfig
from jmoraIs.infrastructure.managed_secrets import (
    EphemeralSecretProvider, InMemorySecretSecurityAudit, ProviderReadySecretAdapter,
)
from jmoraIs.infrastructure.secret_persistence import PostgreSQLKeyMetadataRepository
from jmoraIs.secrets.domain import (
    KeyReference, KeyState, ManagedKeyMetadata, SecretPurpose, SecretReference,
)
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def oidc():
    return OIDCProviderConfig("homologation-oidc", "https://issuer.test", "jmorais-api",
        "https://issuer.test/.well-known/openid-configuration", "https://issuer.test/jwks",
        ("RS256",), 30, ("sub", "iat", "exp", "auth_time", "roles", "organization_id"),
        "roles", "organization_id", (("service", "INTERNAL_SERVICE"),))


_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_JWK = {**jwt.algorithms.RSAAlgorithm.to_jwk(_KEY.public_key(), as_dict=True),
        "kid": "homologation-key", "alg": "RS256", "use": "sig"}


class JwksResponse:
    def raise_for_status(self): pass
    def json(self): return {"keys": [_JWK]}


def identity_http_get(_url, timeout): return JwksResponse()

def secret_refs():
    database=SecretReference("test-vault","postgresql/homologation",SecretPurpose.POSTGRESQL_CREDENTIALS,"1")
    key=KeyReference("test-vault","pseudonymization/hmac","1",SecretPurpose.PSEUDONYMIZATION_HMAC)
    return database,key

class SecretClient:
    available=True
    def __init__(self,database_url): self.database_url=database_url
    def resolve(self,reference,version,purpose):
        if reference=="postgresql/homologation": return self.database_url.encode()
        if reference=="pseudonymization/hmac": return b"p"*32
        raise KeyError(reference)

def secrets(database_url):
    return ProviderReadySecretAdapter("test-vault",SecretClient(database_url),InMemorySecretSecurityAudit())


def migrated_engine():
    url = os.getenv("JMORAIS_TEST_POSTGRES_URL")
    if not url: pytest.skip("JMORAIS_TEST_POSTGRES_URL is required")
    config = Config("alembic.ini"); config.set_main_option("sqlalchemy.url", url); command.upgrade(config, "head")
    return url, create_engine(url, future=True)


@pytest.mark.integration
def test_homologation_composition_and_startup_self_check_succeed():
    url, engine = migrated_engine(); metrics = OpenTelemetryCompatibleMetricsAdapter(InMemoryOpenTelemetryExporter())
    database,key=secret_refs(); PostgreSQLKeyMetadataRepository(engine).save(
        ManagedKeyMetadata(key,KeyState.ACTIVE,NOW,NOW,None,None,"secrets-policy-v1"))
    composition = compose_homologation(homologation_config(database, oidc(), key), identity_http_get=identity_http_get,
        metrics=metrics, structured_log=InMemoryStructuredLog(),secrets_provider=secrets(url))
    assert composition.app and composition.reviewer_governance and not composition.api_services.missing()
    assert composition.operational_services.readiness.check().ready


def test_homologation_composition_fails_when_postgresql_is_unavailable():
    url = "postgresql+psycopg://invalid:invalid@127.0.0.1:1/invalid?connect_timeout=1"
    database,key=secret_refs()
    with pytest.raises(HomologationStartupError):
        compose_homologation(homologation_config(database, oidc(), key), identity_http_get=identity_http_get,
            metrics=OpenTelemetryCompatibleMetricsAdapter(InMemoryOpenTelemetryExporter()),
            structured_log=InMemoryStructuredLog(),secrets_provider=secrets(url))

def test_homologation_rejects_development_secret_provider_before_resolution():
    database,key=secret_refs(); ephemeral=EphemeralSecretProvider({})
    with pytest.raises(HomologationStartupError,match="development secret providers"):
        compose_homologation(homologation_config(database,oidc(),key),identity_http_get=identity_http_get,
            metrics=OpenTelemetryCompatibleMetricsAdapter(InMemoryOpenTelemetryExporter()),
            structured_log=InMemoryStructuredLog(),secrets_provider=ephemeral)


@pytest.mark.parametrize("failed", ["audit_backend", "migrations"])
def test_startup_self_check_fails_for_audit_or_stale_migration(failed):
    names = ("postgresql", "migrations", "repository_composition", "audit_backend",
        "metrics_backend", "authentication_backend", "critical_governance")
    checks = tuple(ReadinessCheck(name, name != failed, "STALE" if name == failed else "AVAILABLE") for name in names)
    with pytest.raises(HomologationStartupError): startup_self_check(ReadinessReport(checks))


@pytest.mark.integration
def test_api_audit_is_durable_append_only_and_has_no_payload_column():
    _, engine = migrated_engine(); adapter = PostgreSQLApiAccessAuditAdapter(engine)
    identifier = "api_" + uuid4().hex
    correlation = "audit-" + uuid4().hex
    event = ApiAccessAuditEvent(identifier, "svc-1", "INTERNAL_SERVICE",
        "INTERNAL_OPERATIONS", correlation, "api-access-v1", "/internal/api/v1/version",
        "GET", "ALLOWED", 200, 1.5, NOW)
    adapter.append(event)
    assert adapter.history(correlation)[-1] == event
    with pytest.raises(IntegrityError): adapter.append(event)
    with pytest.raises(DBAPIError), engine.begin() as connection:
        connection.execute(text("UPDATE api_access_audit_events SET status_code=500 WHERE event_id=:id"), {"id": event.event_id})
    with pytest.raises(DBAPIError), engine.begin() as connection:
        connection.execute(text("DELETE FROM api_access_audit_events WHERE event_id=:id"), {"id": event.event_id})
    with engine.connect() as connection:
        columns = {row[0] for row in connection.execute(text("""SELECT column_name FROM information_schema.columns
            WHERE table_name='api_access_audit_events'"""))}
    assert not {"payload", "patient_id", "patient_context", "evidence_package"}.intersection(columns)
