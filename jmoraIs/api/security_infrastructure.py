from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass

from .security import (
    ApiAccessAuditEvent, ApiLogRecord, ApiMetric, CallerContext, CallerCredentials, CallerRole,
    PurposeOfUse, ReadinessCheck, ReadinessReport,
)


class AuthenticationRejected(RuntimeError): pass


@dataclass(frozen=True)
class DevelopmentIdentity:
    caller_id: str
    role: CallerRole
    token_sha256: str
    allowed_purposes: tuple[PurposeOfUse, ...]
    policy_version: str
    principal_type: str = "SERVICE"

    @classmethod
    def from_token(cls, caller_id: str, role: CallerRole, token: str,
                   allowed_purposes: tuple[PurposeOfUse, ...], policy_version: str,
                   principal_type: str | None = None):
        if not caller_id or len(token) < 24 or not allowed_purposes or not policy_version:
            raise ValueError("complete development identity configuration is required")
        kind = principal_type or ("SERVICE" if role is CallerRole.INTERNAL_SERVICE else "HUMAN")
        if kind not in {"HUMAN", "SERVICE"}:
            raise ValueError("development principal type is invalid")
        return cls(caller_id, role, hashlib.sha256(token.encode()).hexdigest(), allowed_purposes,
                   policy_version, kind)


class DeterministicDevelopmentAuthenticator:
    """Local/homologation adapter only; tokens are never persisted in clear text."""
    def __init__(self, identities: tuple[DevelopmentIdentity, ...]): self._identities = identities
    def readiness(self) -> ReadinessCheck:
        return ReadinessCheck("authentication_backend", bool(self._identities),
                              "AVAILABLE" if self._identities else "UNAVAILABLE")
    def authenticate(self, credentials: CallerCredentials, correlation_id: str) -> CallerContext:
        if not credentials.bearer_token: raise AuthenticationRejected("authentication is required")
        try: purpose = PurposeOfUse(credentials.purpose)
        except (ValueError, TypeError) as exc: raise AuthenticationRejected("a valid purpose is required") from exc
        digest = hashlib.sha256(credentials.bearer_token.encode()).hexdigest()
        identity = next((item for item in self._identities if hmac.compare_digest(item.token_sha256, digest)), None)
        if identity is None: raise AuthenticationRejected("caller credentials are invalid")
        if purpose not in identity.allowed_purposes: raise AuthenticationRejected("purpose is not authorized for caller")
        return CallerContext(identity.caller_id, identity.role, purpose, correlation_id, identity.policy_version,
                             (identity.role,), "development", "development", identity.principal_type, ())

    @property
    def homologation_safe(self) -> bool: return False


class InMemoryApiAccessAudit:
    def __init__(self): self.events: list[ApiAccessAuditEvent] = []
    def append(self, event: ApiAccessAuditEvent) -> None: self.events.append(event)


class InMemoryApiMetrics:
    def __init__(self): self.metrics: list[ApiMetric] = []
    def observe(self, metric: ApiMetric) -> None: self.metrics.append(metric)


class InMemoryOpenTelemetryExporter:
    def __init__(self): self.counters = []; self.histograms = []
    def add_counter(self, name, value, attributes): self.counters.append((name, value, dict(attributes)))
    def record_histogram(self, name, value, attributes): self.histograms.append((name, value, dict(attributes)))


class InMemoryStructuredLog:
    def __init__(self): self.records: list[ApiLogRecord] = []
    def emit(self, record: ApiLogRecord) -> None: self.records.append(record)


class OpenTelemetryCompatibleMetricsAdapter:
    def __init__(self, exporter): self._exporter = exporter
    def readiness(self) -> ReadinessCheck:
        return ReadinessCheck("metrics_backend", self._exporter is not None,
                              "AVAILABLE" if self._exporter is not None else "UNAVAILABLE")
    def observe(self, metric: ApiMetric) -> None:
        attributes = {"route": metric.route_template, "method": metric.method,
                      "status_code": str(metric.status_code), "outcome": metric.outcome}
        self._exporter.add_counter("jmorais.api.requests", 1, attributes)
        self._exporter.record_histogram("jmorais.api.duration_ms", metric.duration_ms, attributes)
        self._exporter.add_counter(f"jmorais.api.status.{metric.status_code}", 1, attributes)
        if metric.status_code == 401: self._exporter.add_counter("jmorais.api.authentication_failures", 1, attributes)
        if metric.status_code == 403: self._exporter.add_counter("jmorais.api.authorization_failures", 1, attributes)
        if metric.route_template.endswith("/health/ready") and metric.status_code == 503:
            self._exporter.add_counter("jmorais.api.readiness_failures", 1, attributes)
        if metric.outcome == "AUDIT_FAILURE": self._exporter.add_counter("jmorais.api.audit_failures", 1, attributes)
        if metric.route_template == "/identity/token-validation":
            self._exporter.add_counter("jmorais.iam.authentication_success" if metric.status_code == 200
                else "jmorais.iam.authentication_failure", 1, attributes)
            self._exporter.record_histogram("jmorais.iam.token_validation_ms", metric.duration_ms, attributes)
        if metric.route_template == "/identity/jwks-refresh":
            self._exporter.add_counter("jmorais.iam.key_refresh", 1, attributes)
            self._exporter.add_counter("jmorais.iam.provider_available" if metric.status_code == 200
                else "jmorais.iam.provider_unavailable", 1, attributes)
        if metric.outcome == "IDENTITY_LINK_FAILURE":
            self._exporter.add_counter("jmorais.iam.identity_link_failure", 1, attributes)
        if metric.route_template == "/security/secrets/resolve":
            self._exporter.record_histogram("jmorais.secrets.resolution_ms",metric.duration_ms,attributes)
            self._exporter.add_counter("jmorais.secrets.resolution_success" if metric.status_code==200
                else "jmorais.secrets.resolution_failure",1,attributes)
            self._exporter.add_counter("jmorais.kms.available" if metric.status_code==200
                else "jmorais.kms.unavailable",1,attributes)


class StaticReadinessProbe:
    def __init__(self, checks: tuple[ReadinessCheck, ...]): self._checks = checks
    def check(self) -> ReadinessReport: return ReadinessReport(self._checks)
