from __future__ import annotations

from typing import Protocol

from .security import ApiAccessAuditEvent, ApiLogRecord, ApiMetric, CallerContext, CallerCredentials, ReadinessReport


class ApiAuthenticationPort(Protocol):
    def authenticate(self, credentials: CallerCredentials, correlation_id: str) -> CallerContext: ...


class ApiAuthorizationPort(Protocol):
    def authorize(self, caller: CallerContext, resource_class: str) -> None: ...


class ApiAccessAuditPort(Protocol):
    def append(self, event: ApiAccessAuditEvent) -> None: ...


class ApiMetricsPort(Protocol):
    def observe(self, metric: ApiMetric) -> None: ...


class ApiStructuredLogPort(Protocol):
    def emit(self, record: ApiLogRecord) -> None: ...


class OpenTelemetryMetricExporterPort(Protocol):
    def add_counter(self, name: str, value: int, attributes: dict[str, str]) -> None: ...
    def record_histogram(self, name: str, value: float, attributes: dict[str, str]) -> None: ...


class ApiReadinessPort(Protocol):
    def check(self) -> ReadinessReport: ...
