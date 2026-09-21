from __future__ import annotations
from dataclasses import replace
from datetime import datetime,timezone
from uuid import uuid4
from sqlalchemy import text
from jmoraIs.tenancy.context import current_tenant_context
from jmoraIs.governed_llm_draft.exact_reference_persistence import PostgreSQLGovernedLLMDraftExactReferenceRepository
from jmoraIs.llm_gateway.exact_reference_persistence import PostgreSQLLLMInvocationExactReferenceRepository
from .application import validate_review_chain
from .domain import LLMHumanReviewEvent
from .persistence import LLMHumanReviewJsonCodec
from .exact_reference import *

class PostgreSQLHumanReviewExactReferenceRepository:
    def __init__(self,engine,draft_references,*,clock=None,codec=None):
        if engine.dialect.name!="postgresql":raise ValueError("exact human review references require PostgreSQL")
        self._engine=engine;self._draft_references=draft_references;self._clock=clock or (lambda:datetime.now(timezone.utc));self._codec=codec or LLMHumanReviewJsonCodec()
    def reference_for(self,event:LLMHumanReviewEvent,draft_reference:PersistedGovernedLLMDraftReference):
        if not isinstance(event,LLMHumanReviewEvent):raise HumanReviewReferenceRejected("typed review event is required")
        draft=self._draft_references.get_exact(draft_reference);canonical=self._validate_exact(event.review_event_id)
        if canonical!=event:raise HumanReviewReferenceRejected("review event does not match canonical persistence")
        if (draft.draft_id,draft.version,draft.invocation_id,draft.tenant_id)!=(event.draft_id,event.draft_version,event.invocation_id,event.tenant_id):raise HumanReviewReferenceRejected("review event/draft linkage mismatch")
        tenant=current_tenant_context()
        if tenant.tenant_id!=event.tenant_id:raise HumanReviewReferenceRejected("review tenant mismatch")
        unsigned=PersistedHumanReviewReference("hrr_"+uuid4().hex,event.review_event_id,draft_reference,event.stream_position,event.tenant_id,
            event.reviewer_id,event.reviewer_role.value,event.decision.value,event.resulting_state.value,event.policy_version,event.request_id,
            event.correlation_id,event.predecessor_event_id,event.previous_hash,event.integrity_hash,"0"*64,self._clock())
        reference=replace(unsigned,integrity_hash=human_review_reference_integrity(unsigned))
        with self._engine.begin() as c:c.execute(text("""INSERT INTO human_review_persisted_references
          (reference_id,review_event_id,draft_reference_id,draft_reference_integrity_hash,stream_position,tenant_id,reviewer_id,
           reviewer_role,decision,resulting_state,policy_version,request_id,correlation_id,predecessor_event_id,previous_hash,
           event_integrity_hash,integrity_hash,issued_at) VALUES(:reference,:event,:draft,:draft_hash,:position,:tenant,:reviewer,
           :role,:decision,:state,:policy,:request,:correlation,:predecessor,:previous,:event_hash,:integrity,:issued)"""),{
          "reference":reference.reference_id,"event":reference.review_event_id,"draft":draft_reference.reference_id,
          "draft_hash":draft_reference.integrity_hash,"position":reference.stream_position,"tenant":reference.tenant_id,
          "reviewer":reference.reviewer_id,"role":reference.reviewer_role,"decision":reference.decision,"state":reference.resulting_state,
          "policy":reference.policy_version,"request":reference.request_id,"correlation":reference.correlation_id,
          "predecessor":reference.predecessor_event_id,"previous":reference.previous_hash,"event_hash":reference.event_integrity_hash,
          "integrity":reference.integrity_hash,"issued":reference.issued_at})
        return reference
    def get_exact(self,reference):
        if not validate_human_review_reference(reference):raise HumanReviewReferenceRejected("authentic owner-issued review reference is required")
        tenant=current_tenant_context()
        if tenant.tenant_id!=reference.tenant_id:raise HumanReviewReferenceRejected("review tenant mismatch")
        with self._engine.connect() as c:row=c.execute(text("SELECT * FROM human_review_persisted_references WHERE reference_id=:id"),{"id":reference.reference_id}).mappings().first()
        if row is None:raise LegacyMissingPersistedHumanReviewReference("LEGACY_MISSING_PERSISTED_HUMAN_REVIEW_REFERENCE")
        draft_reference=self._load_draft_reference(row)
        persisted=self._decode_reference(row,draft_reference)
        if persisted!=reference:raise HumanReviewReferenceRejected("persisted review reference mismatch")
        draft=self._draft_references.get_exact(draft_reference);event=self._validate_exact(reference.review_event_id)
        if (event.draft_id,event.draft_version,event.invocation_id)!=(draft.draft_id,draft.version,draft.invocation_id):raise HumanReviewReferenceRejected("review/draft exact linkage mismatch")
        actual=(event.review_event_id,event.stream_position,event.tenant_id,event.reviewer_id,event.reviewer_role.value,event.decision.value,event.resulting_state.value,event.policy_version,event.request_id,event.correlation_id,event.predecessor_event_id,event.previous_hash,event.integrity_hash)
        expected=(reference.review_event_id,reference.stream_position,reference.tenant_id,reference.reviewer_id,reference.reviewer_role,reference.decision,reference.resulting_state,reference.policy_version,reference.request_id,reference.correlation_id,reference.predecessor_event_id,reference.previous_hash,reference.event_integrity_hash)
        if actual!=expected:return self._reject("review exact linkage mismatch")
        return event
    @staticmethod
    def _reject(message):raise HumanReviewReferenceRejected(message)
    def _validate_exact(self,event_id):
        with self._engine.connect() as c:
            row=c.execute(text("SELECT * FROM llm_human_review_events WHERE review_event_id=:id"),{"id":event_id}).mappings().first()
            if row is None:raise LegacyMissingPersistedHumanReviewReference("LEGACY_MISSING_PERSISTED_HUMAN_REVIEW_REFERENCE")
            rows=c.execute(text("SELECT payload FROM llm_human_review_events WHERE draft_id=:draft AND stream_position<=:position ORDER BY stream_position"),{"draft":row["draft_id"],"position":row["stream_position"]}).scalars().all()
        events=tuple(self._codec.decode(v) for v in rows)
        if not validate_review_chain(events) or len(events)!=row["stream_position"] or events[-1].review_event_id!=event_id:raise HumanReviewReferenceRejected("review hash chain is invalid")
        event=events[-1]
        actual=tuple(row[k] for k in ("review_event_id","draft_id","draft_version","invocation_id","request_id","correlation_id","tenant_id","organization_id","prior_state","resulting_state","decision","reviewer_id","reviewer_role","policy_version","occurred_at","stream_position","predecessor_event_id","previous_hash","integrity_hash"))
        expected=(event.review_event_id,event.draft_id,event.draft_version,event.invocation_id,event.request_id,event.correlation_id,event.tenant_id,event.organization_id,event.prior_state.value,event.resulting_state.value,event.decision.value,event.reviewer_id,event.reviewer_role.value,event.policy_version,event.occurred_at,event.stream_position,event.predecessor_event_id,event.previous_hash,event.integrity_hash)
        if actual!=expected:raise HumanReviewReferenceRejected("review relational/payload mismatch")
        return event
    def _load_draft_reference(self,row):
        with self._engine.connect() as c:
            draft_row=c.execute(text("SELECT * FROM governed_llm_draft_persisted_references WHERE reference_id=:id"),{"id":row["draft_reference_id"]}).mappings().first()
            invocation_row=c.execute(text("SELECT * FROM llm_invocation_persisted_references WHERE reference_id=:id"),{"id":draft_row["invocation_reference_id"] if draft_row else None}).mappings().first()
        if draft_row is None or invocation_row is None:raise HumanReviewReferenceRejected("typed draft reference is unavailable")
        invocation=PostgreSQLLLMInvocationExactReferenceRepository._decode_reference(invocation_row)
        draft=PostgreSQLGovernedLLMDraftExactReferenceRepository._decode_reference(draft_row,invocation)
        if draft.integrity_hash!=row["draft_reference_integrity_hash"]:raise HumanReviewReferenceRejected("draft reference integrity mismatch")
        return draft
    @staticmethod
    def _decode_reference(row,draft):return PersistedHumanReviewReference(row["reference_id"],row["review_event_id"],draft,row["stream_position"],row["tenant_id"],row["reviewer_id"],row["reviewer_role"],row["decision"],row["resulting_state"],row["policy_version"],row["request_id"],row["correlation_id"],row["predecessor_event_id"],row["previous_hash"],row["event_integrity_hash"],row["integrity_hash"],row["issued_at"])
