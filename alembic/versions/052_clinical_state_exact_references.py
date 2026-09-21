"""Owner-issued exact Clinical State and timeline references."""
from alembic import op
import sqlalchemy as sa


revision = "052_clinical_state_exact_refs"
down_revision = "051_patient_context_exact_ref"
branch_labels = None
depends_on = None


def _secure(table):
    op.execute(f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
               "FOR EACH ROW EXECUTE FUNCTION reject_immutable_history_mutation()")
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY {table}_tenant_isolation ON {table} "
               "USING (tenant_id = NULLIF(current_setting('jmorais.tenant_id', true), '')) "
               "WITH CHECK (tenant_id = NULLIF(current_setting('jmorais.tenant_id', true), ''))")
    op.execute(f"GRANT SELECT,INSERT ON {table} TO jmorais_application_writer")
    op.execute(f"GRANT SELECT ON {table} TO jmorais_application_reader")
    op.execute(f"REVOKE UPDATE,DELETE,TRUNCATE ON {table} FROM jmorais_application_writer,jmorais_application_reader")


def upgrade():
    op.create_table("clinical_state_persisted_references",
        sa.Column("sequence_id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("reference_id", sa.String(68), nullable=False, unique=True),
        sa.Column("state_id", sa.String(67), sa.ForeignKey("patient_clinical_state_versions.state_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("state_version", sa.Integer, nullable=False),
        sa.Column("pseudonymous_patient_id", sa.String(67), nullable=False),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("policy_version", sa.String(128), nullable=False),
        sa.Column("predecessor_reference_id", sa.String(68), sa.ForeignKey("clinical_state_persisted_references.reference_id", ondelete="RESTRICT")),
        sa.Column("predecessor_state_version", sa.Integer),
        sa.Column("provenance_reference", sa.String(128), nullable=False),
        sa.Column("state_integrity_hash", sa.String(64), nullable=False),
        sa.Column("integrity_hash", sa.String(64), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "state_id", "state_version", name="uq_clinical_state_exact_reference"),
        sa.CheckConstraint("state_version > 0", name="ck_clinical_state_reference_version"),
        sa.CheckConstraint("length(state_integrity_hash)=64", name="ck_clinical_state_reference_state_hash"),
        sa.CheckConstraint("length(integrity_hash)=64", name="ck_clinical_state_reference_integrity"),
        sa.CheckConstraint("(state_version=1 AND predecessor_reference_id IS NULL AND predecessor_state_version IS NULL) OR (state_version>1 AND predecessor_reference_id IS NOT NULL AND predecessor_state_version=state_version-1)", name="ck_clinical_state_reference_predecessor"))
    op.create_index("ix_clinical_state_reference_exact", "clinical_state_persisted_references",
                    ["tenant_id", "reference_id", "state_id", "state_version"])

    op.create_table("clinical_state_timeline_references",
        sa.Column("sequence_id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("timeline_reference_id", sa.String(68), nullable=False, unique=True),
        sa.Column("pseudonymous_patient_id", sa.String(67), nullable=False),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("policy_version", sa.String(128), nullable=False),
        sa.Column("member_count", sa.Integer, nullable=False),
        sa.Column("integrity_hash", sa.String(64), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("member_count > 0", name="ck_clinical_state_timeline_member_count"),
        sa.CheckConstraint("length(integrity_hash)=64", name="ck_clinical_state_timeline_integrity"))
    op.create_index("ix_clinical_state_timeline_exact", "clinical_state_timeline_references",
                    ["tenant_id", "timeline_reference_id", "pseudonymous_patient_id"])

    op.create_table("clinical_state_timeline_reference_members",
        sa.Column("sequence_id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("timeline_reference_id", sa.String(68), sa.ForeignKey("clinical_state_timeline_references.timeline_reference_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("position", sa.Integer, nullable=False),
        sa.Column("state_reference_id", sa.String(68), sa.ForeignKey("clinical_state_persisted_references.reference_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.UniqueConstraint("timeline_reference_id", "position", name="uq_clinical_state_timeline_position"),
        sa.UniqueConstraint("timeline_reference_id", "state_reference_id", name="uq_clinical_state_timeline_member"),
        sa.CheckConstraint("position > 0", name="ck_clinical_state_timeline_position"))
    op.create_index("ix_clinical_state_timeline_members", "clinical_state_timeline_reference_members",
                    ["tenant_id", "timeline_reference_id", "position"])

    for table in ("clinical_state_persisted_references", "clinical_state_timeline_references",
                  "clinical_state_timeline_reference_members"):
        _secure(table)
        op.execute(f"GRANT USAGE,SELECT ON SEQUENCE {table}_sequence_id_seq TO jmorais_application_writer")


def downgrade():
    raise RuntimeError("exact Clinical State reference history cannot be destructively downgraded")
