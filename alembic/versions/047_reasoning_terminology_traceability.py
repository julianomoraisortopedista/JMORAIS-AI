"""Exact terminology-governance lineage for ClinicalReasoningInput."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision="047_reasoning_term_ref"
down_revision="046_guideline_exact_ref"
branch_labels=None
depends_on=None

def upgrade():
    op.create_table("terminology_mapping_governance_references",
      sa.Column("sequence_id",sa.BigInteger,sa.Identity(),primary_key=True),
      sa.Column("reference_id",sa.String(68),nullable=False,unique=True),
      sa.Column("governance_record_id",sa.String(68),sa.ForeignKey("terminology_mapping_governance_versions.governance_record_id",ondelete="RESTRICT"),nullable=False),
      sa.Column("record_version",sa.Integer,nullable=False),sa.Column("target_concept_id",sa.String(256)),
      sa.Column("terminology_version",sa.String(128),nullable=False),sa.Column("source_reference",sa.String(256),nullable=False),
      sa.Column("mapping_type",sa.String(32),nullable=False),sa.Column("classification",sa.String(64),nullable=False),
      sa.Column("policy_version",sa.String(128),nullable=False),sa.Column("integrity_hash",sa.String(64),nullable=False),
      sa.Column("issued_at",sa.DateTime(timezone=True),nullable=False),
      sa.UniqueConstraint("governance_record_id",name="uq_terminology_governance_exact_reference"),
      sa.CheckConstraint("record_version>0",name="ck_terminology_governance_reference_version"),
      sa.CheckConstraint("length(integrity_hash)=64",name="ck_terminology_governance_reference_integrity"),
      sa.CheckConstraint("classification='SHARED_GLOBAL_REFERENCE'",name="ck_terminology_governance_reference_classification"))
    op.create_index("ix_terminology_governance_reference_exact","terminology_mapping_governance_references",["reference_id","governance_record_id","record_version"])
    op.execute("CREATE TRIGGER terminology_mapping_governance_references_append_only BEFORE UPDATE OR DELETE ON terminology_mapping_governance_references FOR EACH ROW EXECUTE FUNCTION reject_immutable_history_mutation()")
    op.add_column("clinical_reasoning_input_versions",sa.Column("terminology_governance_references",postgresql.JSONB,nullable=False,server_default=sa.text("'[]'::jsonb")))
    op.create_check_constraint("ck_reasoning_terminology_references_array","clinical_reasoning_input_versions","jsonb_typeof(terminology_governance_references)='array'")
    op.execute("GRANT SELECT,INSERT ON terminology_mapping_governance_references TO jmorais_application_writer")
    op.execute("GRANT SELECT ON terminology_mapping_governance_references TO jmorais_application_reader")
    op.execute("GRANT USAGE,SELECT ON SEQUENCE terminology_mapping_governance_references_sequence_id_seq TO jmorais_application_writer")
    op.execute("REVOKE UPDATE,DELETE,TRUNCATE ON terminology_mapping_governance_references FROM jmorais_application_writer,jmorais_application_reader")

def downgrade():raise RuntimeError("exact terminology-governance lineage cannot be destructively downgraded")
