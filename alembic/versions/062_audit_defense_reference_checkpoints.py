"""Atomic unit-stream anchors for new Audit Defense owner references; no backfill."""
from alembic import op
revision="062_defense_ref_checkpoints"
down_revision="061_pgi_defense_exact_link"
branch_labels=None
depends_on=None

def upgrade():
    op.execute("""CREATE FUNCTION checkpoint_audit_defense_reference() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
    BEGIN
      INSERT INTO cryptographic_stream_checkpoints
        (stream_namespace,stream_id,stream_position,head_hash,recorded_at)
      VALUES ('audit_defense_persisted_references',NEW.reference_id,1,
        encode(digest(convert_to(concat_ws('|',encode(convert_to(NEW.sequence_id::text,'UTF8'),'hex'),encode(convert_to(NEW.reference_id::text,'UTF8'),'hex'),encode(convert_to(NEW.tenant_id::text,'UTF8'),'hex'),encode(convert_to(NEW.stream_id::text,'UTF8'),'hex'),encode(convert_to(NEW.package_version::text,'UTF8'),'hex'),encode(convert_to(NEW.package_id::text,'UTF8'),'hex'),encode(convert_to(NEW.policy_version::text,'UTF8'),'hex'),encode(convert_to(NEW.integrity_hash::text,'UTF8'),'hex'),encode(convert_to(to_char(NEW.issued_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),'UTF8'),'hex')),'UTF8'),'sha256'),'hex'),NEW.issued_at);
      RETURN NEW;
    END;$$""")
    op.execute("""CREATE TRIGGER audit_defense_reference_checkpoint AFTER INSERT
      ON audit_defense_persisted_references FOR EACH ROW
      EXECUTE FUNCTION checkpoint_audit_defense_reference()""")
    op.execute("GRANT SELECT ON audit_defense_persisted_references TO jmorais_offline_replay_verifier")
    op.execute("REVOKE INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER ON audit_defense_persisted_references FROM jmorais_offline_replay_verifier")

def downgrade():
    raise RuntimeError("Audit Defense reference checkpoints cannot be destructively downgraded")
