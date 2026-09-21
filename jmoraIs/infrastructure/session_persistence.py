from __future__ import annotations

from hashlib import sha256
from sqlalchemy import text

from jmoraIs.api.security import ReadinessCheck
from jmoraIs.identity.domain import PrincipalType
from jmoraIs.identity.session_domain import AuthenticatedSession, SessionIdentifier, SessionRevocationEvent, SessionStatus


class PostgreSQLSessionRepository:
    def __init__(self, engine): self._engine = engine
    def recognize(self, session: AuthenticatedSession) -> AuthenticatedSession:
        with self._engine.begin() as connection:
            connection.execute(text("""INSERT INTO authenticated_sessions
              (session_id,principal_id,tenant_id,organization_id,issuer,principal_type,issued_at,expires_at,policy_version,recognized_at)
              VALUES(:session_id,:principal_id,:tenant_id,:organization_id,:issuer,:principal_type,:issued_at,:expires_at,:policy_version,:recognized_at)
              ON CONFLICT(session_id) DO NOTHING"""), {**session.__dict__, "session_id": _hash_identifier(session.session_id.value),
                "principal_type": session.principal_type.value})
        current = self.get(session.session_id.value)
        if current is None: raise RuntimeError("session recognition failed")
        return current
    def get(self, session_id: str):
        with self._engine.connect() as connection:
            row = connection.execute(text("SELECT * FROM authenticated_sessions WHERE session_id=:id"), {"id": _hash_identifier(session_id)}).mappings().first()
        if row is None: return None
        value = dict(row); value.pop("sequence_id", None)
        return AuthenticatedSession(**{**value, "session_id": SessionIdentifier(session_id),
            "principal_type": PrincipalType(value["principal_type"])})
    def status(self, session_id: str, principal_id: str) -> SessionStatus:
        with self._engine.connect() as connection:
            row = connection.execute(text("""SELECT event_type FROM session_security_events
              WHERE (session_id=:session_id OR session_id IS NULL) AND principal_id=:principal_id
              AND event_type IN ('SESSION_REVOKED','PRINCIPAL_SESSIONS_REVOKED','SESSION_SUSPENDED','SERVICE_CREDENTIAL_REVOKED')
              ORDER BY sequence_id DESC LIMIT 1"""), {"session_id": _hash_identifier(session_id), "principal_id": principal_id}).scalar()
        if row in ("SESSION_REVOKED", "PRINCIPAL_SESSIONS_REVOKED", "SERVICE_CREDENTIAL_REVOKED"): return SessionStatus.REVOKED
        if row == "SESSION_SUSPENDED": return SessionStatus.SUSPENDED
        return SessionStatus.ACTIVE
    def append_event(self, event: SessionRevocationEvent) -> None: _append_event(self._engine, event)
    def readiness(self): return _readiness(self._engine, "authenticated_sessions", "session_repository")


class PostgreSQLReplayProtectionRepository:
    def __init__(self, engine): self._engine = engine
    def consume(self, *, jti_hash, session, consumed_at, single_use):
        with self._engine.begin() as connection:
            result = connection.execute(text("""INSERT INTO token_replay_records
              (jti_hash,session_id,principal_id,tenant_id,issuer,expires_at,consumed_at,single_use,policy_version)
              VALUES(:jti_hash,:session_id,:principal_id,:tenant_id,:issuer,:expires_at,:consumed_at,:single_use,:policy_version)
              ON CONFLICT(jti_hash) DO NOTHING"""), {"jti_hash": jti_hash, "session_id": _hash_identifier(session.session_id.value),
                "principal_id": session.principal_id, "tenant_id": session.tenant_id, "issuer": session.issuer,
                "expires_at": session.expires_at, "consumed_at": consumed_at, "single_use": single_use,
                "policy_version": session.policy_version})
            if result.rowcount == 1: return True
            row = connection.execute(text("SELECT session_id,principal_id,issuer,single_use FROM token_replay_records WHERE jti_hash=:hash"),
                {"hash": jti_hash}).mappings().one()
            matches = row["session_id"] == _hash_identifier(session.session_id.value) and row["principal_id"] == session.principal_id and row["issuer"] == session.issuer
            return bool(matches and not row["single_use"] and not single_use)
    def readiness(self): return _readiness(self._engine, "token_replay_records", "replay_repository")


class PostgreSQLSessionSecurityAudit:
    def __init__(self, engine): self._engine = engine
    def append(self, event): _append_event(self._engine, event)
    def readiness(self): return _readiness(self._engine, "session_security_events", "session_audit")


def _append_event(engine, event):
    with engine.begin() as connection:
        connection.execute(text("""INSERT INTO session_security_events
          (event_id,event_type,session_id,principal_id,tenant_id,reason_code,correlation_id,policy_version,occurred_at)
          VALUES(:event_id,:event_type,:session_id,:principal_id,:tenant_id,:reason_code,:correlation_id,:policy_version,:occurred_at)
          ON CONFLICT(event_id) DO NOTHING"""), {**event.__dict__, "event_type": event.event_type.value,
            "session_id": _hash_identifier(event.session_id) if event.session_id else None})

def _hash_identifier(value: str) -> str: return sha256(value.encode()).hexdigest()

def _readiness(engine, table, name):
    try:
        with engine.connect() as connection: connection.execute(text(f"SELECT 1 FROM {table} LIMIT 1"))
        return ReadinessCheck(name, True, "AVAILABLE")
    except Exception: return ReadinessCheck(name, False, "UNAVAILABLE")
