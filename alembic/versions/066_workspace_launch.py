"""Prospective immutable clinical launch authorizations; no historical backfill."""
from alembic import op
import sqlalchemy as sa

revision = '066_workspace_launch'
down_revision = '065_defense_reference_state'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('clinical_workspace_launches',
        sa.Column('launch_id', sa.String(80), primary_key=True),
        sa.Column('tenant_id', sa.String(128), nullable=False),
        sa.Column('payload', sa.Text, nullable=False),
        sa.Column('integrity_hash', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    op.execute('''CREATE TRIGGER clinical_workspace_launch_append_only BEFORE UPDATE OR DELETE
        ON clinical_workspace_launches FOR EACH ROW EXECUTE FUNCTION reject_immutable_history_mutation()''')
    op.execute('ALTER TABLE clinical_workspace_launches ENABLE ROW LEVEL SECURITY')
    op.execute('''CREATE POLICY clinical_workspace_launch_tenant ON clinical_workspace_launches
        USING (tenant_id=NULLIF(current_setting('jmorais.tenant_id',true),''))
        WITH CHECK (tenant_id=NULLIF(current_setting('jmorais.tenant_id',true),''))''')
    op.execute('GRANT SELECT,INSERT ON clinical_workspace_launches TO jmorais_application_writer')
    op.execute('GRANT SELECT ON clinical_workspace_launches TO jmorais_application_reader,jmorais_offline_replay_verifier')
    op.execute('REVOKE UPDATE,DELETE,TRUNCATE ON clinical_workspace_launches FROM jmorais_application_writer,jmorais_application_reader')
    op.execute('REVOKE INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER ON clinical_workspace_launches FROM jmorais_offline_replay_verifier')
    op.execute('''CREATE FUNCTION checkpoint_clinical_workspace_launch() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
        BEGIN
          IF encode(sha256(convert_to(NEW.payload,'UTF8')),'hex') <> NEW.integrity_hash THEN
            RAISE EXCEPTION 'launch integrity rejected';
          END IF;
          INSERT INTO cryptographic_stream_checkpoints
            (stream_namespace,stream_id,stream_position,head_hash,recorded_at)
          VALUES ('clinical_workspace_launches',NEW.launch_id,1,NEW.integrity_hash,NEW.created_at);
          RETURN NEW;
        END;$$''')
    op.execute('''CREATE TRIGGER clinical_workspace_launch_checkpoint AFTER INSERT ON clinical_workspace_launches
        FOR EACH ROW EXECUTE FUNCTION checkpoint_clinical_workspace_launch()''')


def downgrade():
    raise RuntimeError('launch authorizations cannot be destructively downgraded')
