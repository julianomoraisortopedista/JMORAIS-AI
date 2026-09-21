from __future__ import annotations

from jmoraIs.application.integrity_alerts import IntegrityAlert


class InMemoryIntegrityAlertAdapter:
    def __init__(self) -> None:
        self._alerts: list[IntegrityAlert] = []

    def publish(self, alert: IntegrityAlert) -> None:
        self._alerts.append(alert)

    @property
    def alerts(self) -> tuple[IntegrityAlert, ...]:
        return tuple(self._alerts)
