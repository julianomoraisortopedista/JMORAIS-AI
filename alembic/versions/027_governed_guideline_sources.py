"""Canonical shared governed guideline source history."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision="027_governed_guideline_sources";down_revision="026_clinical_appraisal_history";branch_labels=None;depends_on=None
def upgrade():
    op.create_table("governed_guideline_source_versions",
      sa.Column("sequence_id",sa.BigInteger,sa.Identity(),primary_key=True),sa.Column("record_id",sa.String(68),nullable=False,unique=True),
      sa.Column("guideline_id",sa.String(128),nullable=False,index=True),sa.Column("source_version_identifier",sa.String(128),nullable=False),
      sa.Column("record_version",sa.Integer,nullable=False),sa.Column("predecessor_record_id",sa.String(68)),sa.Column("governance_status",sa.String(32),nullable=False),
      sa.Column("appraisal_reference",sa.String(128),nullable=False),sa.Column("appraisal_version",sa.String(64),nullable=False),
      sa.Column("provenance_references",postgresql.JSONB,nullable=False),sa.Column("policy_version",sa.String(64),nullable=False),
      sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),sa.Column("payload",postgresql.JSONB,nullable=False),
      sa.UniqueConstraint("guideline_id","record_version",name="uq_governed_guideline_record_version"),
      sa.CheckConstraint("record_version>0",name="ck_governed_guideline_record_version"))
    op.execute("CREATE TRIGGER governed_guideline_sources_append_only BEFORE UPDATE OR DELETE ON governed_guideline_source_versions FOR EACH ROW EXECUTE FUNCTION reject_immutable_history_mutation()")
    op.execute("GRANT SELECT,INSERT ON governed_guideline_source_versions TO jmorais_application_writer")
    op.execute("GRANT SELECT ON governed_guideline_source_versions TO jmorais_application_reader")
    op.execute("GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO jmorais_application_writer")
def downgrade():raise RuntimeError("governed guideline history cannot be destructively downgraded")
