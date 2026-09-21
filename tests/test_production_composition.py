from dataclasses import replace
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from jmoraIs.api.configuration import (
    BuildMetadata, InternalApiEnvironment, RuntimeSecurityPolicy, production_config,
)
from jmoraIs.api.production import ProductionStartupError, compose_production
from jmoraIs.api.production_asgi import create
from jmoraIs.identity.configuration import OIDCProviderConfig
from jmoraIs.secrets.domain import KeyReference, SecretPurpose, SecretReference
from jmoraIs.infrastructure.production_runtime import CURRENT_SCHEMA_REVISION, EXPECTED_APPEND_ONLY_TABLES

ROOT = Path(__file__).resolve().parents[1]

def config():
    oidc = OIDCProviderConfig("provider", "https://issuer", "aud", "https://issuer/discovery", "https://issuer/jwks",
        ("RS256",), 10, ("sub", "iat", "exp", "auth_time", "roles", "organization_id"), "roles", "organization_id",
        (("svc", "INTERNAL_SERVICE"),))
    return production_config(SecretReference("vault", "db", SecretPurpose.POSTGRESQL_CREDENTIALS, "1"), oidc,
        KeyReference("vault", "pseudo", "1", SecretPurpose.PSEUDONYMIZATION_HMAC),
        BuildMetadata("release-1", "build-1", "abc123", "2026-08-10T00:00:00Z"),
        offline_replay_database_credential=SecretReference(
            "vault", "offline-replay", SecretPurpose.OFFLINE_REPLAY_DATABASE_CREDENTIAL, "1"))

def test_production_configuration_requires_external_security_and_bounded_runtime():
    value = config()
    assert value.environment is InternalApiEnvironment.PRODUCTION and value.database_url is None
    assert value.runtime_security == RuntimeSecurityPolicy()
    with pytest.raises(ValueError): replace(value, build_metadata=None)
    with pytest.raises(ValueError): replace(value, offline_replay_database_credential=value.database_credential)
    with pytest.raises(ValueError): replace(value, offline_replay_database_credential=SecretReference(
        value.database_credential.provider, value.database_credential.reference,
        SecretPurpose.OFFLINE_REPLAY_DATABASE_CREDENTIAL, "different-purpose"))
    with pytest.raises(ValueError): RuntimeSecurityPolicy(concurrency_limit=0)

def test_production_rejects_dev_observability_secrets_and_wrong_profile():
    class Unsafe: production_safe = False; homologation_safe = False
    with pytest.raises(ProductionStartupError, match="observability"):
        compose_production(config(), metrics=Unsafe(), structured_log=Unsafe(), identity_http_get=None, secrets_provider=Unsafe())
    safe = type("Safe", (), {"production_safe": True})()
    with pytest.raises(ProductionStartupError, match="secret"):
        compose_production(config(), metrics=safe, structured_log=safe, identity_http_get=None, secrets_provider=Unsafe())

def test_production_asgi_has_no_fallback(monkeypatch):
    monkeypatch.delenv("JMORAIS_PRODUCTION_COMPOSITION_FACTORY", raising=False)
    with pytest.raises(ProductionStartupError, match="explicit"): create()

def test_docker_security_and_architecture_contracts():
    docker = (ROOT / "Dockerfile").read_text(); ignore = (ROOT / ".dockerignore").read_text()
    assert docker.count("FROM ") >= 2 and "python:3.12-alpine@sha256:" in docker
    assert docker.count("python:3.12-alpine@sha256:") == 2
    assert "USER 10001:10001" in docker and "--limit-concurrency" in docker
    assert "--timeout-graceful-shutdown" in docker and "HEALTHCHECK" in docker
    assert "JMORAIS_DEV_INTERNAL_TOKEN" not in docker and "PASSWORD=" not in docker
    assert ".env*" in ignore and "*secret*" in ignore

def test_production_composition_is_explicit_and_no_clinical_logging():
    source = (ROOT / "jmoraIs/api/production.py").read_text()
    asgi = (ROOT / "jmoraIs/api/production_asgi.py").read_text()
    assert "compose_production" in source and "DeterministicDevelopmentAuthenticator" not in source
    assert "InMemory" not in source and "jmoraIs.api.asgi" not in asgi
    logging = (ROOT / "jmoraIs/infrastructure/api_observability.py").read_text().lower()
    assert "patientcontext" in logging and "evidencepackage" in logging
    assert '"correlation_id"' in logging and '"route_template"' in logging

def test_production_schema_gate_tracks_the_single_alembic_head():
    alembic = Config(str(ROOT / "alembic.ini"))
    alembic.set_main_option("script_location", str(ROOT / "alembic"))
    assert ScriptDirectory.from_config(alembic).get_heads() == [CURRENT_SCHEMA_REVISION]
    production_source = (ROOT / "jmoraIs" / "api" / "production.py").read_text()
    assert '"025_production_composition"' not in production_source

def test_production_gate_requires_all_release_critical_immutable_streams():
    required = {
        "persisted_gateway_inputs", "cryptographic_stream_checkpoints", "llm_invocations",
        "governed_llm_drafts", "governed_llm_draft_lifecycle_events",
        "llm_human_review_events", "llm_human_review_security_events",
        "medical_document_versions", "audit_defense_versions",
    }
    assert required.issubset(EXPECTED_APPEND_ONLY_TABLES)
