"""Add completeness checkpoints for mandatory Stage-13/14 streams."""
from alembic import op

revision="040_stage14_crypto_checkpoints";down_revision="039_review_security_audit";branch_labels=None;depends_on=None
STREAMS=(
    ("governed_llm_draft_lifecycle_events","draft_id","integrity_hash"),
    ("llm_human_review_events","draft_id","integrity_hash"),
    ("llm_human_review_security_events","correlation_id","integrity_hash"),
)
def upgrade():
    op.execute("""CREATE OR REPLACE FUNCTION record_tenant_cryptographic_stream_checkpoint()
    RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
    BEGIN
      INSERT INTO cryptographic_stream_checkpoints(stream_namespace,stream_id,stream_position,head_hash,recorded_at)
      VALUES(TG_TABLE_NAME,(to_jsonb(NEW)->>'tenant_id')||'|'||(to_jsonb(NEW)->>TG_ARGV[0]),
        (to_jsonb(NEW)->>'stream_position')::bigint,to_jsonb(NEW)->>TG_ARGV[1],
        (to_jsonb(NEW)->>'occurred_at')::timestamptz);
      RETURN NEW;
    END;$$""")
    for table,owner,event_hash in STREAMS:
        op.execute(f"""INSERT INTO cryptographic_stream_checkpoints(stream_namespace,stream_id,stream_position,head_hash,recorded_at)
          SELECT '{table}',tenant_id||'|'||{owner},stream_position,{event_hash},occurred_at FROM {table} ON CONFLICT DO NOTHING""")
        op.execute(f"""CREATE TRIGGER {table}_crypto_checkpoint AFTER INSERT ON {table}
          FOR EACH ROW EXECUTE FUNCTION record_tenant_cryptographic_stream_checkpoint('{owner}','{event_hash}')""")
def downgrade():raise RuntimeError("Stage-14 completeness checkpoints cannot be destructively downgraded")
