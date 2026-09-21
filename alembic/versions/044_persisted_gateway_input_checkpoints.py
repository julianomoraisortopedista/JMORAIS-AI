"""Atomically anchor new PersistedGatewayInput trust records."""
from alembic import op

revision="044_pgi_checkpoints"
down_revision="043_persisted_gateway_inputs"
branch_labels=None
depends_on=None


def upgrade():
    # Each PersistedGatewayInput is one immutable, position-1 stream. Existing
    # rows are deliberately not backfilled: no independent historical anchor
    # existed when they were written.
    op.execute("""CREATE OR REPLACE FUNCTION record_persisted_gateway_input_checkpoint()
    RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
    BEGIN
      INSERT INTO cryptographic_stream_checkpoints
        (stream_namespace,stream_id,stream_position,head_hash,recorded_at)
      VALUES
        ('persisted_gateway_inputs',NEW.tenant_id||'|'||NEW.persisted_gateway_input_id,
         1,NEW.record_integrity_hash,NEW.issued_at);
      RETURN NEW;
    END;$$""")
    op.execute("""CREATE TRIGGER persisted_gateway_inputs_crypto_checkpoint
      AFTER INSERT ON persisted_gateway_inputs FOR EACH ROW
      EXECUTE FUNCTION record_persisted_gateway_input_checkpoint()""")


def downgrade():
    raise RuntimeError("PersistedGatewayInput completeness anchors cannot be destructively downgraded")
