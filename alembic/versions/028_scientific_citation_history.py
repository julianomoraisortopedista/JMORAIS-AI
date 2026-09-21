"""Canonical append-only scientific citation history."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision="028_scientific_citation_history";down_revision="027_governed_guideline_sources";branch_labels=None;depends_on=None
def upgrade():
    op.create_table("scientific_citation_record_versions",sa.Column("sequence_id",sa.BigInteger,sa.Identity(),primary_key=True),
      sa.Column("citation_record_id",sa.String(64),nullable=False,unique=True),sa.Column("evidence_package_id",sa.String(64),sa.ForeignKey("evidence_package_catalog.package_id",ondelete="RESTRICT"),nullable=False,index=True),
      sa.Column("publication_identity_id",sa.String(64),nullable=False),sa.Column("version",sa.Integer,nullable=False),sa.Column("predecessor_record_id",sa.String(64),sa.ForeignKey("scientific_citation_record_versions.citation_record_id",ondelete="RESTRICT")),
      sa.Column("publication_status",sa.String(40),nullable=False),sa.Column("policy_version",sa.String(64),nullable=False),
      sa.Column("formatter_version",sa.String(64),nullable=False),sa.Column("rendered_vancouver",sa.Text,nullable=False),
      sa.Column("metadata_payload",postgresql.JSONB,nullable=False),sa.Column("linkage_payload",postgresql.JSONB,nullable=False),
      sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),sa.Column("integrity_hash",sa.String(64),nullable=False),
      sa.UniqueConstraint("evidence_package_id","version",name="uq_scientific_citation_package_version"),sa.CheckConstraint("version>0",name="ck_scientific_citation_version_positive"))
    op.execute("CREATE TRIGGER scientific_citation_history_append_only BEFORE UPDATE OR DELETE ON scientific_citation_record_versions FOR EACH ROW EXECUTE FUNCTION reject_immutable_history_mutation()")
    op.execute("GRANT SELECT,INSERT ON scientific_citation_record_versions TO jmorais_application_writer")
    op.execute("GRANT SELECT ON scientific_citation_record_versions TO jmorais_application_reader")
    op.execute("GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO jmorais_application_writer")
def downgrade():raise RuntimeError("scientific citation history cannot be destructively downgraded")
