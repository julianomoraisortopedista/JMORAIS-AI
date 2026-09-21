from __future__ import annotations

from dataclasses import replace

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from jmoraIs.api.security import ReadinessCheck
from jmoraIs.identity.domain import (
    ExternalIdentityLink, IdentityLinkStatus, IdentitySecurityEvent, IdentitySecurityEventType, PrincipalType,
)


class PostgreSQLExternalIdentityLinkRepository:
    def __init__(self, engine): self._engine = engine
    def create(self, link: ExternalIdentityLink) -> None:
        with self._engine.begin() as connection:
            statement = text("""INSERT INTO external_identity_links
                (principal_id,provider,external_subject,organization_id,status,principal_type,
                 tenant_id,allowed_purposes,scoped_permissions,reviewer_id,created_at,last_seen_at,policy_version)
                VALUES(:principal_id,:provider,:external_subject,:organization_id,:status,:principal_type,:tenant_id,
                 :allowed_purposes,:scoped_permissions,:reviewer_id,:created_at,:last_seen_at,:policy_version)""").bindparams(
                     bindparam("allowed_purposes", type_=JSONB), bindparam("scoped_permissions", type_=JSONB))
            connection.execute(statement,
                {**link.__dict__, "status": link.status.value, "principal_type": link.principal_type.value,
                 "allowed_purposes": list(link.allowed_purposes), "scoped_permissions": list(link.scoped_permissions)})
    def get(self, provider, external_subject):
        with self._engine.connect() as connection:
            row = connection.execute(text("SELECT * FROM external_identity_links WHERE provider=:provider "
                "AND external_subject=:subject"), {"provider": provider, "subject": external_subject}).mappings().first()
        if row is None: return None
        value = dict(row); value.pop("sequence_id", None)
        return ExternalIdentityLink(**{**value, "status": IdentityLinkStatus(value["status"]),
            "principal_type": PrincipalType(value["principal_type"]),
            "allowed_purposes": tuple(value["allowed_purposes"]),
            "scoped_permissions": tuple(value["scoped_permissions"])})
    def set_status(self, provider, external_subject, status, occurred_at):
        current = self.get(provider, external_subject)
        if current is None: raise KeyError("identity link does not exist")
        with self._engine.begin() as connection:
            connection.execute(text("UPDATE external_identity_links SET status=:status,last_seen_at=:seen "
                "WHERE provider=:provider AND external_subject=:subject"),
                {"status": status.value, "seen": occurred_at, "provider": provider, "subject": external_subject})
        return replace(current, status=status, last_seen_at=occurred_at)
    def readiness(self):
        try:
            with self._engine.connect() as connection: connection.execute(text("SELECT 1 FROM external_identity_links LIMIT 1"))
            return ReadinessCheck("identity_repository", True, "AVAILABLE")
        except Exception: return ReadinessCheck("identity_repository", False, "UNAVAILABLE")


class PostgreSQLIdentitySecurityAudit:
    def __init__(self, engine): self._engine = engine
    def append(self, event: IdentitySecurityEvent):
        with self._engine.begin() as connection:
            connection.execute(text("""INSERT INTO identity_security_events
                (event_id,event_type,principal_id,provider,correlation_id,reason_code,policy_version,occurred_at)
                VALUES(:event_id,:event_type,:principal_id,:provider,:correlation_id,:reason_code,:policy_version,:occurred_at)"""),
                {**event.__dict__, "event_type": event.event_type.value})
    def history(self, correlation_id):
        with self._engine.connect() as connection:
            rows = connection.execute(text("SELECT event_id,event_type,principal_id,provider,correlation_id,"
                "reason_code,policy_version,occurred_at FROM identity_security_events "
                "WHERE correlation_id=:id ORDER BY sequence_id"), {"id": correlation_id}).mappings().all()
        return tuple(IdentitySecurityEvent(**{**dict(row), "event_type": IdentitySecurityEventType(row["event_type"])})
                     for row in rows)
