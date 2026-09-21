"""Owner-issued exact orthopedic-set references and document lineage."""
from alembic import op
import sqlalchemy as sa

revision="048_orthopedic_exact_ref"
down_revision="047_reasoning_term_ref"
branch_labels=None
depends_on=None

def upgrade():
    op.create_table("orthopedic_assessment_set_references",
        sa.Column("sequence_id",sa.BigInteger,sa.Identity(),primary_key=True),
        sa.Column("reference_id",sa.String(68),nullable=False,unique=True),
        sa.Column("tenant_id",sa.String(128),nullable=False),
        sa.Column("set_id",sa.String(71),sa.ForeignKey("orthopedic_assessment_versions.set_id",ondelete="RESTRICT"),nullable=False),
        sa.Column("set_version",sa.Integer,nullable=False),
        sa.Column("subject_reference",sa.String(67),nullable=False),
        sa.Column("policy_version",sa.String(64),nullable=False),
        sa.Column("integrity_hash",sa.String(64),nullable=False),
        sa.Column("issued_at",sa.DateTime(timezone=True),nullable=False),
        sa.UniqueConstraint("tenant_id","set_id","set_version",name="uq_orthopedic_set_exact_reference"),
        sa.CheckConstraint("set_version > 0",name="ck_orthopedic_set_reference_version"),
        sa.CheckConstraint("length(integrity_hash)=64",name="ck_orthopedic_set_reference_integrity"))
    op.create_index("ix_orthopedic_set_reference_exact","orthopedic_assessment_set_references",["tenant_id","reference_id","set_id","set_version"])
    op.execute("CREATE TRIGGER orthopedic_assessment_set_references_append_only BEFORE UPDATE OR DELETE ON orthopedic_assessment_set_references FOR EACH ROW EXECUTE FUNCTION reject_immutable_history_mutation()")
    op.execute("ALTER TABLE orthopedic_assessment_set_references ENABLE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY orthopedic_assessment_set_references_tenant_isolation ON orthopedic_assessment_set_references USING (tenant_id = NULLIF(current_setting('jmorais.tenant_id', true), '')) WITH CHECK (tenant_id = NULLIF(current_setting('jmorais.tenant_id', true), ''))")
    op.add_column("medical_document_versions",sa.Column("orthopedic_set_reference_id",sa.String(68),nullable=True))
    op.add_column("medical_document_versions",sa.Column("orthopedic_set_id",sa.String(71),nullable=True))
    op.add_column("medical_document_versions",sa.Column("orthopedic_set_version",sa.Integer,nullable=True))
    op.create_foreign_key("fk_medical_document_orthopedic_reference","medical_document_versions","orthopedic_assessment_set_references",["orthopedic_set_reference_id"],["reference_id"],ondelete="RESTRICT")
    op.create_check_constraint("ck_medical_document_orthopedic_lineage_complete","medical_document_versions","(orthopedic_set_reference_id IS NULL AND orthopedic_set_id IS NULL AND orthopedic_set_version IS NULL) OR (orthopedic_set_reference_id IS NOT NULL AND orthopedic_set_id IS NOT NULL AND orthopedic_set_version > 0)")
    op.create_index("ix_medical_document_orthopedic_lineage","medical_document_versions",["tenant_id","orthopedic_set_reference_id","orthopedic_set_id","orthopedic_set_version"])
    op.execute("GRANT SELECT,INSERT ON orthopedic_assessment_set_references TO jmorais_application_writer")
    op.execute("GRANT SELECT ON orthopedic_assessment_set_references TO jmorais_application_reader")
    op.execute("GRANT USAGE,SELECT ON SEQUENCE orthopedic_assessment_set_references_sequence_id_seq TO jmorais_application_writer")
    op.execute("REVOKE UPDATE,DELETE,TRUNCATE ON orthopedic_assessment_set_references FROM jmorais_application_writer,jmorais_application_reader")

def downgrade():
    raise RuntimeError("exact orthopedic-set reference history cannot be destructively downgraded")
