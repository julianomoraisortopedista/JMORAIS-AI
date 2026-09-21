"""Persist explicit owner-issued Audit Defense linkage without legacy backfill."""
from alembic import op
import sqlalchemy as sa

revision="061_pgi_defense_exact_link"
down_revision="060_ortho_reasoning_lineage"
branch_labels=None
depends_on=None


def upgrade():
    op.add_column("persisted_gateway_inputs",sa.Column("audit_defense_reference_id",sa.String(68)))
    op.create_foreign_key("fk_pgi_defense_exact_reference","persisted_gateway_inputs",
        "audit_defense_persisted_references",["audit_defense_reference_id"],["reference_id"],ondelete="RESTRICT")
    op.execute("""CREATE FUNCTION validate_pgi_defense_exact_link() RETURNS trigger
    LANGUAGE plpgsql SET search_path=public,pg_temp AS $$
    DECLARE r audit_defense_persisted_references%ROWTYPE; link jsonb;
    BEGIN
      link := NEW.payload->'audit_defense_reference';
      IF NEW.artifact_type='AuditDefense' THEN
        IF NEW.audit_defense_reference_id IS NULL OR link IS NULL OR NEW.schema_version<2 THEN
          RAISE EXCEPTION 'LEGACY_MISSING_PERSISTED_DEFENSE_PACKAGE_REFERENCE';
        END IF;
        SELECT * INTO r FROM audit_defense_persisted_references
          WHERE tenant_id=NEW.tenant_id AND reference_id=NEW.audit_defense_reference_id;
        IF NOT FOUND THEN RAISE EXCEPTION 'exact defense reference unavailable'; END IF;
        IF NEW.source_context IS DISTINCT FROM 'audit_defense'
          OR NEW.artifact_id IS DISTINCT FROM r.stream_id
          OR NEW.artifact_version IS DISTINCT FROM r.package_version
          OR NEW.policy_version IS DISTINCT FROM r.policy_version
          OR NEW.integrity_reference IS DISTINCT FROM r.integrity_hash
          OR link->>'reference_id' IS DISTINCT FROM r.reference_id
          OR link->>'stream_id' IS DISTINCT FROM r.stream_id
          OR (link->>'version')::integer IS DISTINCT FROM r.package_version
          OR link->>'package_id' IS DISTINCT FROM r.package_id
          OR link->>'tenant_id' IS DISTINCT FROM r.tenant_id
          OR link->>'policy_version' IS DISTINCT FROM r.policy_version
          OR link->>'integrity_hash' IS DISTINCT FROM r.integrity_hash
          OR (link->>'issued_at')::timestamptz IS DISTINCT FROM r.issued_at
        THEN RAISE EXCEPTION 'exact defense linkage mismatch'; END IF;
      ELSIF NEW.audit_defense_reference_id IS NOT NULL OR link IS NOT NULL THEN
        RAISE EXCEPTION 'unexpected defense reference';
      END IF;
      RETURN NEW;
    END;$$""")
    op.execute("""CREATE TRIGGER persisted_gateway_inputs_defense_exact_link
      BEFORE INSERT ON persisted_gateway_inputs FOR EACH ROW
      EXECUTE FUNCTION validate_pgi_defense_exact_link()""")


def downgrade():
    raise RuntimeError("persisted exact reference linkage cannot be destructively downgraded")
