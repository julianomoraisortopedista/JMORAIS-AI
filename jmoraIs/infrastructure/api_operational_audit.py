from __future__ import annotations

from sqlalchemy import text

from jmoraIs.api.security import ApiAccessAuditEvent, ReadinessCheck


class PostgreSQLApiAccessAuditAdapter:
    """Append-only metadata audit; the schema has no clinical payload column."""
    def __init__(self, engine) -> None: self._engine = engine

    def append(self, event: ApiAccessAuditEvent) -> None:
        with self._engine.begin() as connection:
            connection.execute(text("SELECT set_config('jmorais.tenant_id', :tenant_id, true)"),
                               {"tenant_id": event.tenant_id})
            connection.execute(text("""INSERT INTO api_access_audit_events
                (event_id,caller_id,role,purpose,correlation_id,policy_version,route_template,
                 method,outcome,status_code,duration_ms,occurred_at,tenant_id)
                VALUES (:event_id,:caller_id,:role,:purpose,:correlation_id,:policy_version,:route_template,
                        :method,:outcome,:status_code,:duration_ms,:occurred_at,:tenant_id)"""), event.__dict__)

    def history(self, correlation_id: str) -> tuple[ApiAccessAuditEvent, ...]:
        with self._engine.connect() as connection:
            rows = connection.execute(text("""SELECT event_id,caller_id,role,purpose,correlation_id,
                policy_version,route_template,method,outcome,status_code,duration_ms,occurred_at,tenant_id
                FROM api_access_audit_events WHERE correlation_id=:correlation_id ORDER BY sequence_id"""),
                {"correlation_id": correlation_id}).mappings().all()
        return tuple(ApiAccessAuditEvent(**dict(row)) for row in rows)

    def readiness(self) -> ReadinessCheck:
        try:
            with self._engine.connect() as connection:
                connection.execute(text("SELECT 1 FROM api_access_audit_events LIMIT 1"))
            return ReadinessCheck("audit_backend", True, "AVAILABLE")
        except Exception: return ReadinessCheck("audit_backend", False, "UNAVAILABLE")
