from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class OpenTelemetrySecurityConfig:
    endpoint: str
    allowed_hosts: tuple[str, ...]
    timeout_seconds: int = 5
    max_buffered_points: int = 2_000

    def __post_init__(self) -> None:
        parsed = urlparse(self.endpoint)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.hostname not in self.allowed_hosts
                or "*" in self.allowed_hosts or min(self.timeout_seconds, self.max_buffered_points) < 1):
            raise ValueError("secure bounded telemetry configuration is required")


class BoundedOpenTelemetryExporter:
    """Metadata-only bounded adapter; transport credentials remain behind Secrets/KMS."""

    production_safe = True
    _FORBIDDEN = frozenset({"patient_id", "patient_context", "clinical_payload", "prompt",
        "response", "authorization", "token", "jti", "password", "secret", "dsn"})

    def __init__(self, config: OpenTelemetrySecurityConfig, transport) -> None:
        self._config, self._transport, self._buffer = config, transport, []
        self.dropped_points = 0

    def add_counter(self, name, value, attributes) -> None:
        self._add(("counter", str(name), int(value), self._safe(attributes)))

    def record_histogram(self, name, value, attributes) -> None:
        self._add(("histogram", str(name), float(value), self._safe(attributes)))

    def flush(self) -> None:
        if not self._buffer: return
        batch, self._buffer = tuple(self._buffer), []
        self._transport.export(self._config.endpoint, batch, timeout=self._config.timeout_seconds)

    def _add(self, point) -> None:
        if len(self._buffer) >= self._config.max_buffered_points:
            self.dropped_points += 1
            return
        self._buffer.append(point)

    def _safe(self, attributes):
        normalized = {str(key).casefold(): str(value) for key, value in dict(attributes).items()}
        if self._FORBIDDEN.intersection(normalized):
            raise ValueError("sensitive telemetry attribute is prohibited")
        return normalized
