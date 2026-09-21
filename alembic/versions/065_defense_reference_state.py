"""Explicit Defense reference states; preserve legacy rows without backfill."""
from alembic import op
import sqlalchemy as sa

revision = "065_defense_reference_state"
down_revision = "064_replay_defense_select"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("audit_defense_persisted_references", sa.Column("reference_state", sa.String(24), nullable=True))
    op.create_check_constraint("ck_defense_reference_state", "audit_defense_persisted_references",
        "reference_state IS NULL OR reference_state IN ('PRE_LINK','STAGE11_LINKED')")
    op.execute("""CREATE OR REPLACE FUNCTION checkpoint_audit_defense_reference() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
    BEGIN
      IF NEW.reference_state IS NULL THEN
        RAISE EXCEPTION 'explicit Defense reference state required for new references';
      END IF;
      INSERT INTO cryptographic_stream_checkpoints
        (stream_namespace,stream_id,stream_position,head_hash,recorded_at)
      VALUES ('audit_defense_persisted_references',NEW.reference_id,1,
        encode(sha256(convert_to(concat_ws('|',
          encode(convert_to(NEW.sequence_id::text,'UTF8'),'hex'),
                      encode(convert_to(NEW.reference_id::text,'UTF8'),'hex'),
                      encode(convert_to(NEW.tenant_id::text,'UTF8'),'hex'),
                      encode(convert_to(NEW.stream_id::text,'UTF8'),'hex'),
                      encode(convert_to(NEW.package_version::text,'UTF8'),'hex'),
                      encode(convert_to(NEW.package_id::text,'UTF8'),'hex'),
                      encode(convert_to(NEW.policy_version::text,'UTF8'),'hex'),
                      encode(convert_to(NEW.integrity_hash::text,'UTF8'),'hex'),
                      encode(convert_to(to_char(NEW.issued_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),'UTF8'),'hex'),
                      encode(convert_to(NEW.reference_state,'UTF8'),'hex')
        ),'UTF8')),'hex'),NEW.issued_at);
      RETURN NEW;
    END;$$""")


def downgrade():
    raise RuntimeError("state-bearing exact reference history cannot be destructively downgraded")
