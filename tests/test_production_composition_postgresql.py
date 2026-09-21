from datetime import datetime, timezone
import os

import jwt
import pytest
from alembic import command
from alembic.config import Config
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import create_engine, text

from jmoraIs.api.configuration import BuildMetadata, RuntimeSecurityPolicy, production_config
from jmoraIs.api.production import compose_production
from jmoraIs.api.security_infrastructure import InMemoryOpenTelemetryExporter, InMemoryStructuredLog, OpenTelemetryCompatibleMetricsAdapter
from jmoraIs.identity.configuration import OIDCProviderConfig
from jmoraIs.infrastructure.managed_secrets import InMemorySecretSecurityAudit, ProviderReadySecretAdapter
from jmoraIs.infrastructure.secret_persistence import PostgreSQLKeyMetadataRepository
from jmoraIs.infrastructure.production_runtime import ProductionIntegrityVerifier
from jmoraIs.infrastructure.tenant_database import create_tenant_runtime_engine
from jmoraIs.secrets.domain import KeyReference, KeyState, ManagedKeyMetadata, SecretPurpose, SecretReference

NOW = datetime.now(timezone.utc)

@pytest.fixture(scope="module", autouse=True)
def isolated_database():
    url = os.getenv("JMORAIS_TEST_POSTGRES_URL")
    if not url: yield; return
    owner = create_engine(url, future=True)
    with owner.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE")); connection.execute(text("CREATE SCHEMA public"))
    alembic = Config("alembic.ini"); alembic.set_main_option("sqlalchemy.url", url); command.upgrade(alembic, "head")
    yield
    with owner.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE")); connection.execute(text("CREATE SCHEMA public"))
    owner.dispose()

class ProductionMetrics(OpenTelemetryCompatibleMetricsAdapter): production_safe = True
class ProductionLog(InMemoryStructuredLog):
    production_safe = True
    def flush(self): pass

class SecretClient:
    available = True
    def __init__(self, url): self.url = url
    def resolve(self, reference, version, purpose):
        if reference == "postgresql/production": return self.url.encode()
        if reference == "postgresql/offline-replay": return self.url.encode()
        if reference == "pseudonymization/production": return b"k" * 32
        raise KeyError(reference)

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
JWK = {**jwt.algorithms.RSAAlgorithm.to_jwk(KEY.public_key(), as_dict=True), "kid": "prod-key", "alg": "RS256", "use": "sig"}
class Response:
    def raise_for_status(self): pass
    def json(self): return {"keys": [JWK]}

def test_production_integrity_gate_accepts_current_clean_schema():
    url = os.getenv("JMORAIS_TEST_POSTGRES_URL")
    if not url: pytest.skip("JMORAIS_TEST_POSTGRES_URL is required")
    alembic = Config("alembic.ini"); alembic.set_main_option("sqlalchemy.url", url); command.upgrade(alembic, "head")
    runtime = create_tenant_runtime_engine(url, runtime_role="jmorais_application_writer")
    try:
        checks = ProductionIntegrityVerifier(runtime).check()
        assert checks and all(check.ready for check in checks), checks
    finally:
        runtime.dispose()

def test_production_composition_uses_offline_replay_before_api_startup():
    url = os.getenv("JMORAIS_TEST_POSTGRES_URL")
    if not url: pytest.skip("JMORAIS_TEST_POSTGRES_URL is required")
    alembic = Config("alembic.ini"); alembic.set_main_option("sqlalchemy.url", url); command.upgrade(alembic, "head")
    owner = create_engine(url, future=True)
    database = SecretReference("vault", "postgresql/production", SecretPurpose.POSTGRESQL_CREDENTIALS, "1")
    verifier_database = SecretReference("vault", "postgresql/offline-replay", SecretPurpose.OFFLINE_REPLAY_DATABASE_CREDENTIAL, "1")
    key = KeyReference("vault", "pseudonymization/production", "1", SecretPurpose.PSEUDONYMIZATION_HMAC)
    PostgreSQLKeyMetadataRepository(owner).save(ManagedKeyMetadata(key, KeyState.ACTIVE, NOW, NOW, None, None, "secrets-policy-v1"))
    oidc = OIDCProviderConfig("prod-oidc", "https://issuer", "aud", "https://issuer/discovery", "https://issuer/jwks",
        ("RS256",), 30, ("sub", "iat", "exp", "auth_time", "roles", "organization_id"), "roles", "organization_id", (("svc", "INTERNAL_SERVICE"),))
    config = production_config(database, oidc, key, BuildMetadata("release", "build", "revision", NOW.isoformat()),
        offline_replay_database_credential=verifier_database,
        runtime_security=RuntimeSecurityPolicy(database_tls_required=False))
    provider = ProviderReadySecretAdapter("vault", SecretClient(url), InMemorySecretSecurityAudit())
    composition = compose_production(config, metrics=ProductionMetrics(InMemoryOpenTelemetryExporter()),
        structured_log=ProductionLog(), identity_http_get=lambda *_args, **_kwargs: Response(), secrets_provider=provider)
    try:
        assert composition.integrity_checks and all(check.ready for check in composition.integrity_checks)
        assert not hasattr(composition, "offline_replay_verifier")
        assert not hasattr(composition.app.state, "offline_replay_verifier")
    finally:
        composition.shutdown()
