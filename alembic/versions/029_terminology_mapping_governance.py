"""Append-only terminology mapping governance history."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision="029_terminology_governance";down_revision="028_scientific_citation_history";branch_labels=None;depends_on=None
def upgrade():
    op.create_table("terminology_mapping_governance_versions",
      sa.Column("sequence_id",sa.BigInteger,sa.Identity(),primary_key=True),sa.Column("governance_record_id",sa.String(68),nullable=False,unique=True),
      sa.Column("mapping_stream_id",sa.String(256),nullable=False,index=True),sa.Column("source_reference",sa.String(256),nullable=False,index=True),
      sa.Column("target_concept_id",sa.String(256)),sa.Column("terminology_version",sa.String(128),nullable=False),sa.Column("mapping_type",sa.String(32),nullable=False),
      sa.Column("mapping_confidence",sa.String(16),nullable=False),sa.Column("review_status",sa.String(32),nullable=False),sa.Column("review_required",sa.Boolean,nullable=False),
      sa.Column("policy_version",sa.String(128),nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),sa.Column("version",sa.Integer,nullable=False),
      sa.Column("predecessor_record_id",sa.String(68),sa.ForeignKey("terminology_mapping_governance_versions.governance_record_id",ondelete="RESTRICT")),
      sa.Column("integrity_hash",sa.String(64),nullable=False),sa.Column("payload",postgresql.JSONB,nullable=False),
      sa.UniqueConstraint("mapping_stream_id","version",name="uq_terminology_mapping_governance_stream_version"),sa.CheckConstraint("version>0",name="ck_terminology_mapping_governance_version_positive"))
    op.execute("CREATE TRIGGER terminology_mapping_governance_append_only BEFORE UPDATE OR DELETE ON terminology_mapping_governance_versions FOR EACH ROW EXECUTE FUNCTION reject_immutable_history_mutation()")
    op.execute("GRANT SELECT,INSERT ON terminology_mapping_governance_versions TO jmorais_application_writer")
    op.execute("GRANT SELECT ON terminology_mapping_governance_versions TO jmorais_application_reader")
    op.execute("GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO jmorais_application_writer")
def downgrade():raise RuntimeError("terminology mapping governance history cannot be destructively downgraded")
