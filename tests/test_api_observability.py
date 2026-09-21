from __future__ import annotations

import io
import json
import logging
from datetime import datetime, timezone
import pytest

from fastapi.testclient import TestClient

from jmoraIs.api.app import ApiOperationalServices, create_app
from jmoraIs.api.configuration import (
    InternalApiEnvironment, development_config, homologation_config, test_config as make_test_config,
)
from jmoraIs.api.security import ApiLogRecord, ApiMetric, ReadinessCheck
from jmoraIs.api.security_infrastructure import (
    InMemoryOpenTelemetryExporter, OpenTelemetryCompatibleMetricsAdapter, StaticReadinessProbe,
)
from jmoraIs.infrastructure.api_observability import RedactingJsonLogAdapter
from jmoraIs.identity.configuration import OIDCProviderConfig
from jmoraIs.secrets.domain import KeyReference, SecretPurpose, SecretReference
from tests.test_internal_api import headers, operational, services

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_environment_configuration_excludes_production_and_requires_safe_homologation():
    assert development_config().environment is InternalApiEnvironment.DEVELOPMENT
    assert make_test_config().environment is InternalApiEnvironment.TEST
    with pytest.raises(TypeError): homologation_config("postgresql+psycopg://x:y@localhost/db")
    oidc = OIDCProviderConfig("test-idp", "https://issuer.test", "jmorais-api",
        "https://issuer.test/.well-known/openid-configuration", "https://issuer.test/jwks",
        ("RS256",), 30, ("sub", "iat", "exp", "auth_time", "roles", "organization_id"),
        "roles", "organization_id", (("service", "INTERNAL_SERVICE"),))
    database=SecretReference("vault","database/homologation",SecretPurpose.POSTGRESQL_CREDENTIALS,"1")
    key=KeyReference("vault","pseudonymization","1",SecretPurpose.PSEUDONYMIZATION_HMAC)
    config=homologation_config(database,oidc,key)
    assert config.environment is InternalApiEnvironment.HOMOLOGATION and config.database_url is None
    assert "PRODUCTION" in {item.value for item in InternalApiEnvironment}


def test_opentelemetry_compatible_metrics_emit_required_instruments_without_payload():
    exporter = InMemoryOpenTelemetryExporter(); adapter = OpenTelemetryCompatibleMetricsAdapter(exporter)
    adapter.observe(ApiMetric("/internal/api/v1/version", "GET", 401, 2.5, NOW))
    adapter.observe(ApiMetric("/internal/api/v1/health/ready", "GET", 503, 3.5, NOW))
    adapter.observe(ApiMetric("/internal/api/v1/version", "GET", 503, 1.0, NOW, "AUDIT_FAILURE"))
    names = {item[0] for item in exporter.counters}
    assert {"jmorais.api.requests", "jmorais.api.authentication_failures",
        "jmorais.api.readiness_failures", "jmorais.api.audit_failures"}.issubset(names)
    encoded = repr(exporter.counters) + repr(exporter.histograms)
    assert all(secret not in encoded for secret in ("PatientContext", "EvidencePackage", "Bearer", "password"))


def test_structured_json_logging_redacts_sensitive_values():
    stream = io.StringIO(); logger = logging.getLogger("test.api.redaction"); logger.handlers.clear()
    handler = logging.StreamHandler(stream); logger.addHandler(handler); logger.setLevel(logging.INFO)
    RedactingJsonLogAdapter(logger).emit(ApiLogRecord("corr-1", "Bearer super-secret-token",
        "/internal/api/v1/version", "INTERNAL_OPERATIONS", 200, 1.2, "api-access-v1", NOW))
    payload = json.loads(stream.getvalue())
    assert payload["correlation_id"] == "corr-1" and payload["caller_id"] == "[REDACTED]"
    assert "super-secret" not in stream.getvalue()


def test_correlation_logging_and_ready_degraded_not_ready_transitions():
    ops = operational(); api = TestClient(create_app(services(), ops), headers=headers())
    assert api.get("/internal/api/v1/version", headers={**headers(), "x-correlation-id": "corr-77"}).status_code == 200
    assert ops.structured_log.records[-1].correlation_id == "corr-77"
    degraded_probe = StaticReadinessProbe((ReadinessCheck("postgresql", True, "AVAILABLE"),
        ReadinessCheck("migrations", True, "CURRENT"), ReadinessCheck("critical_dependencies", True, "DEGRADED")))
    degraded_ops = ApiOperationalServices(ops.authentication, ops.authorization, degraded_probe, ops.access_audit,
        ops.metrics, ops.structured_log)
    degraded = TestClient(create_app(services(), degraded_ops), headers=headers()).get("/internal/api/v1/health/ready")
    assert degraded.status_code == 200 and degraded.json()["status"] == "DEGRADED"
    not_ready_ops = operational(ready=False)
    unavailable = TestClient(create_app(services(), not_ready_ops), headers=headers()).get("/internal/api/v1/health/ready")
    assert unavailable.status_code == 503 and unavailable.json()["status"] == "NOT_READY"


def test_audit_failure_fails_closed_and_emits_metric():
    class BrokenAudit:
        def append(self, event): raise RuntimeError("database secret must not leak")
    ops = operational(); guarded = ApiOperationalServices(ops.authentication, ops.authorization, ops.readiness,
        BrokenAudit(), ops.metrics, ops.structured_log)
    response = TestClient(create_app(services(), guarded), headers=headers()).get("/internal/api/v1/version")
    assert response.status_code == 503 and response.json()["code"] == "AUDIT_UNAVAILABLE"
    assert "secret" not in response.text.lower()
    assert any(item.outcome == "AUDIT_FAILURE" for item in ops.metrics.metrics)
