from __future__ import annotations

from sqlalchemy import text
from uuid import uuid4

from jmoraIs.secrets.domain import (
    KeyReference, KeyState, ManagedKeyMetadata, SecretPurpose, SecretSecurityEvent, SecretSecurityEventType,
)


class PostgreSQLKeyMetadataRepository:
    def __init__(self,engine): self._engine=engine
    def get(self,reference):
        with self._engine.connect() as connection:
            row=connection.execute(text("SELECT m.provider,m.key_id,m.key_version,m.purpose,"
                "COALESCE((SELECT e.state FROM managed_key_state_events e WHERE e.provider=m.provider AND e.key_id=m.key_id "
                "AND e.key_version=m.key_version ORDER BY e.sequence_id DESC LIMIT 1),m.state) AS state,"
                "m.created_at,m.activated_at,m.retired_at,m.revoked_at,m.policy_version FROM managed_key_metadata m "
                "WHERE m.provider=:provider AND m.key_id=:key AND m.key_version=:version"),{"provider":reference.provider,"key":reference.key_id,
                "version":reference.version}).mappings().first()
        if row is None:return None
        value=dict(row); key=KeyReference(value.pop("provider"),value.pop("key_id"),value.pop("key_version"),
            SecretPurpose(value.pop("purpose")))
        return ManagedKeyMetadata(key,state=KeyState(value.pop("state")),**value)
    def save(self,metadata):
        with self._engine.begin() as connection:
            connection.execute(text("""INSERT INTO managed_key_metadata
                (provider,key_id,key_version,purpose,state,created_at,activated_at,retired_at,revoked_at,policy_version)
                VALUES(:provider,:key_id,:key_version,:purpose,:state,:created_at,:activated_at,:retired_at,:revoked_at,:policy_version)
                ON CONFLICT(provider,key_id,key_version) DO NOTHING"""),
                {"provider":metadata.reference.provider,"key_id":metadata.reference.key_id,
                 "key_version":metadata.reference.version,"purpose":metadata.reference.purpose.value,
                 "state":metadata.state.value,"created_at":metadata.created_at,"activated_at":metadata.activated_at,
                 "retired_at":metadata.retired_at,"revoked_at":metadata.revoked_at,
                 "policy_version":metadata.policy_version})
            occurred=metadata.revoked_at or metadata.retired_at or metadata.activated_at or metadata.created_at
            connection.execute(text("INSERT INTO managed_key_state_events "
                "(event_id,provider,key_id,key_version,state,occurred_at,policy_version) VALUES "
                "(:event,:provider,:key,:version,:state,:occurred,:policy)"),
                {"event":"keystate_"+uuid4().hex,"provider":metadata.reference.provider,
                 "key":metadata.reference.key_id,"version":metadata.reference.version,"state":metadata.state.value,
                 "occurred":occurred,"policy":metadata.policy_version})


class PostgreSQLSecretSecurityAudit:
    def __init__(self,engine): self._engine=engine
    def append(self,event):
        with self._engine.begin() as connection:
            connection.execute(text("""INSERT INTO secret_security_events
                (event_id,event_type,provider,reference,version,actor_id,purpose,occurred_at,policy_version,outcome)
                VALUES(:event_id,:event_type,:provider,:reference,:version,:actor_id,:purpose,:occurred_at,:policy_version,:outcome)"""),
                {**event.__dict__,"event_type":event.event_type.value,"purpose":event.purpose.value})
    def history(self,reference):
        with self._engine.connect() as connection:
            rows=connection.execute(text("SELECT event_id,event_type,provider,reference,version,actor_id,purpose,"
                "occurred_at,policy_version,outcome FROM secret_security_events WHERE reference=:reference ORDER BY sequence_id"),
                {"reference":reference}).mappings().all()
        return tuple(SecretSecurityEvent(**{**dict(row),"event_type":SecretSecurityEventType(row["event_type"]),
            "purpose":SecretPurpose(row["purpose"])}) for row in rows)
