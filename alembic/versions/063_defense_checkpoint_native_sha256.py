"""Replace only the checkpoint SHA-256 primitive with PostgreSQL native SHA-256."""
from alembic import op

revision="063_defense_native_sha256"
down_revision="062_defense_ref_checkpoints"
branch_labels=None
depends_on=None


def upgrade():
    op.execute('CREATE OR REPLACE FUNCTION checkpoint_audit_defense_reference() RETURNS trigger\n    LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$\n    BEGIN\n      INSERT INTO cryptographic_stream_checkpoints\n        (stream_namespace,stream_id,stream_position,head_hash,recorded_at)\n      VALUES (\'audit_defense_persisted_references\',NEW.reference_id,1,\n        encode(sha256(convert_to(concat_ws(\'|\',encode(convert_to(NEW.sequence_id::text,\'UTF8\'),\'hex\'),encode(convert_to(NEW.reference_id::text,\'UTF8\'),\'hex\'),encode(convert_to(NEW.tenant_id::text,\'UTF8\'),\'hex\'),encode(convert_to(NEW.stream_id::text,\'UTF8\'),\'hex\'),encode(convert_to(NEW.package_version::text,\'UTF8\'),\'hex\'),encode(convert_to(NEW.package_id::text,\'UTF8\'),\'hex\'),encode(convert_to(NEW.policy_version::text,\'UTF8\'),\'hex\'),encode(convert_to(NEW.integrity_hash::text,\'UTF8\'),\'hex\'),encode(convert_to(to_char(NEW.issued_at AT TIME ZONE \'UTC\',\'YYYY-MM-DD"T"HH24:MI:SS.US"Z"\'),\'UTF8\'),\'hex\')),\'UTF8\')),\'hex\'),NEW.issued_at);\n      RETURN NEW;\n    END;$$')


def downgrade():
    raise RuntimeError("cannot restore the unavailable checkpoint hash primitive")
