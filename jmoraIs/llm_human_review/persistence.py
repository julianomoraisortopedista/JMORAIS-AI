from __future__ import annotations

import json
from dataclasses import fields, is_dataclass
from datetime import datetime
from enum import Enum

from sqlalchemy import text

from jmoraIs.clinical.governed import HumanReviewStatus
from jmoraIs.clinical.review_governance import ReviewerRole
from jmoraIs.gateway_input import UpstreamArtifactReference
from jmoraIs.governed_llm_draft import GovernedLLMDraftLifecycleStatus
from jmoraIs.tenancy.context import current_tenant_context

from .application import validate_review_chain, validate_security_chain
from .domain import LLMHumanReviewEvent, LLMHumanReviewRejected, LLMHumanReviewSecurityEvent, LLMHumanReviewSecurityEventType, LLMHumanReviewState, LLMReviewDecision


class LLMHumanReviewJsonCodec:
    schema_version = 1
    _types = {"LLMHumanReviewEvent": LLMHumanReviewEvent, "LLMHumanReviewSecurityEvent": LLMHumanReviewSecurityEvent, "UpstreamArtifactReference": UpstreamArtifactReference}
    _enums = {e.__name__: e for e in (HumanReviewStatus, ReviewerRole, LLMReviewDecision, LLMHumanReviewSecurityEventType)}

    def encode(self, value):
        if is_dataclass(value):
            return {"__type__": type(value).__name__, **{f.name: self.encode(getattr(value, f.name)) for f in fields(value)}}
        if isinstance(value, Enum):
            return {"__enum__": type(value).__name__, "value": value.value}
        if isinstance(value, datetime):
            return {"__datetime__": value.isoformat()}
        if isinstance(value, tuple):
            return {"__tuple__": [self.encode(item) for item in value]}
        return value

    def decode(self, value):
        if isinstance(value, list):
            return tuple(self.decode(item) for item in value)
        if not isinstance(value, dict):
            return value
        if "__enum__" in value:
            return self._enums[value["__enum__"]](value["value"])
        if "__datetime__" in value:
            return datetime.fromisoformat(value["__datetime__"])
        if "__tuple__" in value:
            return tuple(self.decode(item) for item in value["__tuple__"])
        if "__type__" in value:
            cls = self._types[value["__type__"]]
            return cls(**{k: self.decode(v) for k, v in value.items() if k != "__type__"})
        return {k: self.decode(v) for k, v in value.items()}


class InMemoryLLMHumanReviewRepository:
    def __init__(self, lifecycle):
        self._events = []
        self._lifecycle = lifecycle

    def append(self, event):
        if self._lifecycle.current_status(event.draft_id, event.draft_version) is not GovernedLLMDraftLifecycleStatus.ACTIVE:
            raise LLMHumanReviewRejected("draft lifecycle changed before commit")
        history = self.history(event.draft_id)
        if not validate_review_chain(history + (event,)):
            raise LLMHumanReviewRejected("invalid or duplicate review event")
        self._events.append(event)

    def history(self, draft_id):
        return tuple(e for e in self._events if e.draft_id == draft_id)

    def current_state(self, draft_id, version):
        history = tuple(e for e in self.history(draft_id) if e.draft_version == version)
        if not history:
            return None
        event = history[-1]
        return LLMHumanReviewState(draft_id, version, event.resulting_state, event.review_event_id, False)

    def by_invocation(self, invocation_id):
        return tuple(e for e in self._events if e.invocation_id == invocation_id)

    def by_correlation(self, correlation_id):
        return tuple(e for e in self._events if e.correlation_id == correlation_id)


class PostgreSQLLLMHumanReviewRepository:
    def __init__(self, engine, codec=None):
        self._engine = engine
        self._codec = codec or LLMHumanReviewJsonCodec()

    def append(self, event):
        tenant = current_tenant_context()
        if tenant.tenant_id != event.tenant_id or tenant.organization_id != event.organization_id:
            raise LLMHumanReviewRejected("review event tenant scope mismatch")
        with self._engine.begin() as connection:
            # The lifecycle writer uses this identical lock key. This closes the
            # ACTIVE-at-load / revoked-before-commit race.
            connection.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"), {"key": "governed_llm_draft_lifecycle:" + event.draft_id})
            status = connection.execute(text("SELECT resulting_status FROM governed_llm_draft_lifecycle_events WHERE draft_id=:id ORDER BY stream_position DESC LIMIT 1"), {"id": event.draft_id}).scalar_one_or_none()
            if status != GovernedLLMDraftLifecycleStatus.ACTIVE.value:
                raise LLMHumanReviewRejected("draft lifecycle changed before commit")
            history = self._history(connection, event.draft_id)
            if not validate_review_chain(history + (event,)):
                raise LLMHumanReviewRejected("invalid or duplicate review event")
            connection.execute(text("""INSERT INTO llm_human_review_events
                (review_event_id,draft_id,draft_version,invocation_id,request_id,correlation_id,tenant_id,organization_id,
                 prior_state,resulting_state,decision,reviewer_id,reviewer_role,policy_version,occurred_at,stream_position,
                 predecessor_event_id,previous_hash,integrity_hash,payload,schema_version)
                VALUES (:event,:draft,:version,:invocation,:request,:correlation,:tenant,:organization,:prior,:result,:decision,
                 :reviewer,:role,:policy,:occurred,:position,:predecessor,:previous,:integrity,CAST(:payload AS jsonb),:schema)"""), {
                "event": event.review_event_id, "draft": event.draft_id, "version": event.draft_version,
                "invocation": event.invocation_id, "request": event.request_id, "correlation": event.correlation_id,
                "tenant": event.tenant_id, "organization": event.organization_id, "prior": event.prior_state.value,
                "result": event.resulting_state.value, "decision": event.decision.value, "reviewer": event.reviewer_id,
                "role": event.reviewer_role.value, "policy": event.policy_version, "occurred": event.occurred_at,
                "position": event.stream_position, "predecessor": event.predecessor_event_id,
                "previous": event.previous_hash, "integrity": event.integrity_hash,
                "payload": json.dumps(self._codec.encode(event), sort_keys=True, separators=(",", ":")),
                "schema": self._codec.schema_version,
            })

    def history(self, draft_id):
        current_tenant_context()
        with self._engine.connect() as connection:
            return self._history(connection, draft_id)

    def current_state(self, draft_id, version):
        history = tuple(e for e in self.history(draft_id) if e.draft_version == version)
        if not history:
            return None
        event = history[-1]
        return LLMHumanReviewState(draft_id, version, event.resulting_state, event.review_event_id, False)

    def by_invocation(self, invocation_id):
        return self._query("invocation_id", invocation_id)

    def by_correlation(self, correlation_id):
        return self._query("correlation_id", correlation_id)

    def _query(self, column, value):
        current_tenant_context()
        with self._engine.connect() as connection:
            rows = connection.execute(text(f"SELECT payload FROM llm_human_review_events WHERE {column}=:value ORDER BY sequence_id"), {"value": value}).scalars().all()
        events = tuple(self._codec.decode(row) for row in rows)
        if not self._validate_grouped(events):
            raise LLMHumanReviewRejected("persisted review history integrity is invalid")
        return events

    def _history(self, connection, draft_id):
        rows = connection.execute(text("SELECT payload FROM llm_human_review_events WHERE draft_id=:id ORDER BY stream_position"), {"id": draft_id}).scalars().all()
        events = tuple(self._codec.decode(row) for row in rows)
        if not validate_review_chain(events):
            raise LLMHumanReviewRejected("persisted review history integrity is invalid")
        return events

    @staticmethod
    def _validate_grouped(events):
        return all(validate_review_chain(tuple(e for e in events if e.draft_id == draft_id)) for draft_id in {e.draft_id for e in events})


class InMemoryLLMHumanReviewSecurityAudit:
    def __init__(self): self._events=[]
    def append(self,event):
        history=self.history(event.correlation_id)
        if not validate_security_chain(history+(event,)):raise LLMHumanReviewRejected("invalid security audit chain")
        self._events.append(event)
    def history(self,correlation_id):return tuple(x for x in self._events if x.correlation_id==correlation_id)


class PostgreSQLLLMHumanReviewSecurityAudit:
    def __init__(self,engine,codec=None):self._engine=engine;self._codec=codec or LLMHumanReviewJsonCodec()
    def append(self,event):
        tenant=current_tenant_context()
        if event.tenant_id!=tenant.tenant_id or event.organization_id!=tenant.organization_id:raise LLMHumanReviewRejected("security audit tenant mismatch")
        with self._engine.begin() as connection:
            connection.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),{"key":"llm_human_review_security:"+event.correlation_id})
            history=self._history(connection,event.correlation_id)
            if not validate_security_chain(history+(event,)):raise LLMHumanReviewRejected("invalid security audit chain")
            connection.execute(text("""INSERT INTO llm_human_review_security_events
                (event_id,event_type,draft_id,draft_version,invocation_id,request_id,correlation_id,tenant_id,principal_id,
                 reviewer_id,reviewer_role,organization_id,result,reason_code,policy_version,occurred_at,stream_position,
                 previous_hash,integrity_hash,payload,schema_version)
                VALUES(:id,:type,:draft,:version,:invocation,:request,:correlation,:tenant,:principal,:reviewer,:role,
                 :organization,:result,:reason,:policy,:at,:position,:previous,:integrity,CAST(:payload AS jsonb),:schema)"""),{
                "id":event.event_id,"type":event.event_type.value,"draft":event.draft_id,"version":event.draft_version,
                "invocation":event.invocation_id,"request":event.request_id,"correlation":event.correlation_id,"tenant":event.tenant_id,
                "principal":event.principal_id,"reviewer":event.reviewer_id,"role":event.reviewer_role,"organization":event.organization_id,
                "result":event.result,"reason":event.reason_code,"policy":event.policy_version,"at":event.occurred_at,
                "position":event.stream_position,"previous":event.previous_hash,"integrity":event.integrity_hash,
                "payload":json.dumps(self._codec.encode(event),sort_keys=True,separators=(",",":")),"schema":self._codec.schema_version})
    def history(self,correlation_id):
        current_tenant_context()
        with self._engine.connect() as connection:return self._history(connection,correlation_id)
    def _history(self,connection,correlation_id):
        values=connection.execute(text("SELECT payload FROM llm_human_review_security_events WHERE correlation_id=:id ORDER BY stream_position"),{"id":correlation_id}).scalars().all()
        events=tuple(self._codec.decode(x) for x in values)
        if not validate_security_chain(events):raise LLMHumanReviewRejected("persisted security audit integrity is invalid")
        return events
