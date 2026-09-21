"""Canonical shared Clinical Appraisal history."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision="026_clinical_appraisal_history";down_revision="025_production_composition";branch_labels=None;depends_on=None
def upgrade():
    op.create_table("clinical_appraisal_records",
      sa.Column("sequence_id",sa.BigInteger,sa.Identity(),primary_key=True),sa.Column("appraisal_id",sa.String(64),nullable=False,unique=True),
      sa.Column("evidence_package_id",sa.String(64),nullable=False,index=True),sa.Column("recommendation_reference",sa.String(128),nullable=False,index=True),
      sa.Column("framework",sa.String(128),nullable=False),sa.Column("framework_version",sa.String(64),nullable=False),
      sa.Column("appraisal_version",sa.Integer,nullable=False),sa.Column("predecessor_appraisal_id",sa.String(64)),sa.Column("status",sa.String(32),nullable=False),
      sa.Column("payload",postgresql.JSONB,nullable=False),sa.Column("provenance_references",postgresql.JSONB,nullable=False),
      sa.Column("reviewer_reference",sa.String(128)),sa.Column("reviewer_status",sa.String(32),nullable=False),sa.Column("policy_version",sa.String(64),nullable=False),
      sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),sa.Column("superseded_by",sa.String(64)),sa.Column("integrity_hash",sa.String(64),nullable=False),
      sa.UniqueConstraint("recommendation_reference","appraisal_version",name="uq_clinical_appraisal_version"),sa.CheckConstraint("appraisal_version>0",name="ck_clinical_appraisal_version"))
    op.execute("CREATE TRIGGER clinical_appraisal_records_append_only BEFORE UPDATE OR DELETE ON clinical_appraisal_records FOR EACH ROW EXECUTE FUNCTION reject_immutable_history_mutation()")
    op.execute("GRANT SELECT,INSERT ON clinical_appraisal_records TO jmorais_application_writer")
    op.execute("GRANT SELECT ON clinical_appraisal_records TO jmorais_application_reader")
    op.execute("GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO jmorais_application_writer")
def downgrade():raise RuntimeError("clinical appraisal history cannot be destructively downgraded")
