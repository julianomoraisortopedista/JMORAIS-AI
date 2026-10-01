"""Prospective lifecycle authority; immutable history, mutable owner projection.

No legacy pointer or reference backfill. Runtime cannot write the projection.
"""
from alembic import op

revision = '067_evidence_lifecycle_authority'
down_revision = '066_workspace_launch'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('ALTER TABLE governed_evidence_persisted_references ADD COLUMN lifecycle_reference jsonb')
    op.execute('''CREATE TABLE evidence_lifecycle_current (
        tenant_id varchar(128) NOT NULL,
        governed_evidence_id varchar(128) NOT NULL,
        event_id varchar(64) NOT NULL,
        stream_position bigint NOT NULL CHECK (stream_position > 0),
        event_hash varchar(64) NOT NULL,
        PRIMARY KEY (tenant_id, governed_evidence_id))''')
    op.execute('ALTER TABLE evidence_lifecycle_current ENABLE ROW LEVEL SECURITY')
    op.execute('''CREATE POLICY evidence_lifecycle_current_tenant ON evidence_lifecycle_current
        USING (tenant_id=NULLIF(current_setting('jmorais.tenant_id',true),''))
        WITH CHECK (tenant_id=NULLIF(current_setting('jmorais.tenant_id',true),''))''')
    op.execute('GRANT SELECT ON evidence_lifecycle_current TO jmorais_application_writer,jmorais_application_reader,jmorais_offline_replay_verifier')
    op.execute('REVOKE INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER ON evidence_lifecycle_current FROM PUBLIC,jmorais_application_writer,jmorais_application_reader,jmorais_offline_replay_verifier')
    op.execute('''CREATE FUNCTION advance_evidence_lifecycle_authority() RETURNS trigger
      LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
      BEGIN
        INSERT INTO evidence_lifecycle_current
          (tenant_id,governed_evidence_id,event_id,stream_position,event_hash)
        VALUES (NEW.tenant_id,NEW.governed_evidence_id,NEW.event_id,NEW.stream_position,NEW.event_hash)
        ON CONFLICT (tenant_id,governed_evidence_id) DO UPDATE SET
          event_id=EXCLUDED.event_id,stream_position=EXCLUDED.stream_position,event_hash=EXCLUDED.event_hash
        WHERE evidence_lifecycle_current.stream_position=EXCLUDED.stream_position-1
          AND evidence_lifecycle_current.event_hash=NEW.previous_event_hash;
        IF NOT FOUND THEN RAISE EXCEPTION 'lifecycle authority transition rejected'; END IF;
        INSERT INTO cryptographic_stream_checkpoints
          (stream_namespace,stream_id,stream_position,head_hash,recorded_at)
        VALUES ('evidence_lifecycle_current',NEW.tenant_id||'|'||NEW.governed_evidence_id,
                NEW.stream_position,NEW.event_hash,NEW.occurred_at);
        RETURN NEW;
      END;$$''')
    op.execute('REVOKE ALL ON FUNCTION advance_evidence_lifecycle_authority() FROM PUBLIC')
    op.execute('''CREATE TRIGGER evidence_lifecycle_authority AFTER INSERT
      ON governed_evidence_lifecycle_events FOR EACH ROW
      EXECUTE FUNCTION advance_evidence_lifecycle_authority()''')


def downgrade():
    raise RuntimeError('lifecycle authority cannot be destructively downgraded')
