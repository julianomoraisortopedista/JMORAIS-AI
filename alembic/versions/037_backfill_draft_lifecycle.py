"""Backfill canonical lifecycle for drafts issued before lifecycle deployment."""
from alembic import op
from sqlalchemy import text
from dataclasses import asdict
from hashlib import sha256
import json
from jmoraIs.governed_llm_draft.domain import GovernedLLMDraftLifecycleEvent,GovernedLLMDraftLifecycleStatus
from jmoraIs.governed_llm_draft.lifecycle import lifecycle_event
from jmoraIs.governed_llm_draft.persistence import GovernedLLMDraftJsonCodec

revision="037_backfill_draft_lifecycle";down_revision="036_draft_lifecycle";branch_labels=None;depends_on=None

def upgrade():
    connection=op.get_bind();codec=GovernedLLMDraftJsonCodec()
    rows=connection.execute(text("SELECT payload FROM governed_llm_drafts ORDER BY tenant_id,draft_stream_id,version")).scalars().all()
    streams={}
    for payload in rows:
        draft=codec.decode(payload);streams.setdefault((draft.tenant_id,draft.draft_stream_id),[]).append(draft)
    for drafts in streams.values():
        for index,draft in enumerate(drafts):
            existing=connection.execute(text("SELECT 1 FROM governed_llm_draft_lifecycle_events WHERE draft_id=:id LIMIT 1"),{"id":draft.draft_id}).scalar()
            if existing:continue
            active=lifecycle_event(draft,GovernedLLMDraftLifecycleStatus.ACTIVE,"CANONICAL_ISSUANCE","lifecycle-backfill",draft.policy_version,draft.issued_at)
            _insert(connection,active,codec)
            if index<len(drafts)-1:
                successor=drafts[index+1]
                superseded=lifecycle_event(draft,GovernedLLMDraftLifecycleStatus.SUPERSEDED,"REPLACED_BY:"+successor.draft_id,"lifecycle-backfill",draft.policy_version,successor.issued_at,(active,))
                _insert(connection,superseded,codec)

def _insert(connection,event,codec):
    connection.execute(text("INSERT INTO governed_llm_draft_lifecycle_events(lifecycle_event_id,draft_id,draft_version,tenant_id,stream_position,prior_status,resulting_status,reason_reference,actor_reference,policy_version,occurred_at,predecessor_event_id,previous_hash,integrity_hash,payload,schema_version) VALUES(:id,:draft,:version,:tenant,:position,:prior,:result,:reason,:actor,:policy,:at,:predecessor,:previous_hash,:integrity,CAST(:payload AS jsonb),:schema)"),{"id":event.lifecycle_event_id,"draft":event.draft_id,"version":event.draft_version,"tenant":event.tenant_id,"position":event.stream_position,"prior":event.prior_status.value if event.prior_status else None,"result":event.resulting_status.value,"reason":event.reason_reference,"actor":event.actor_reference,"policy":event.policy_version,"at":event.occurred_at,"predecessor":event.predecessor_event_id,"previous_hash":event.previous_hash,"integrity":event.integrity_hash,"payload":json.dumps(codec.encode(event),sort_keys=True,separators=(",",":")),"schema":codec.schema_version})

def downgrade():raise RuntimeError("draft lifecycle backfill cannot be destructively downgraded")
