"""Create the immutable authorized clinical-ingestion Stage-1 artifact."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision="041_authorized_ingestion_records"
down_revision="040_stage14_crypto_checkpoints"
branch_labels=None
depends_on=None


def upgrade():
    op.create_table("authorized_clinical_ingestion_records",
        sa.Column("sequence_id",sa.BigInteger,sa.Identity(),primary_key=True),
        sa.Column("ingestion_record_id",sa.String(80),nullable=False,unique=True),
        sa.Column("tenant_id",sa.String(128),nullable=False),
        sa.Column("pseudonymous_patient_id",sa.String(67),nullable=False),
        sa.Column("patient_context_id",sa.String(64),sa.ForeignKey("patient_context_versions.context_id",ondelete="RESTRICT"),nullable=False),
        sa.Column("patient_context_version",sa.Integer,nullable=False),
        sa.Column("source",sa.String(128),nullable=False),
        sa.Column("source_reference_id",sa.String(160),nullable=False),
        sa.Column("actor_reference",sa.String(128),nullable=False),
        sa.Column("organization_id",sa.String(128),nullable=False),
        sa.Column("purpose",sa.String(48),nullable=False),
        sa.Column("legal_basis_reference",sa.String(128),nullable=False),
        sa.Column("authorization_decision_reference",sa.String(128),nullable=False),
        sa.Column("correlation_id",sa.String(128),nullable=False),
        sa.Column("issued_at",sa.DateTime(timezone=True),nullable=False),
        sa.Column("integrity_hash",sa.String(64),nullable=False),
        sa.Column("payload",postgresql.JSONB,nullable=False),
        sa.Column("schema_version",sa.Integer,nullable=False),
        sa.UniqueConstraint("tenant_id","patient_context_id","patient_context_version",name="uq_authorized_ingestion_context_version"),
        sa.CheckConstraint("patient_context_version > 0",name="ck_authorized_ingestion_context_version"),
        sa.CheckConstraint("length(trim(tenant_id)) > 0",name="ck_authorized_ingestion_tenant"),
        sa.CheckConstraint("length(integrity_hash)=64",name="ck_authorized_ingestion_integrity"))
    op.create_index("ix_authorized_ingestion_tenant_patient","authorized_clinical_ingestion_records",["tenant_id","pseudonymous_patient_id"])
    op.create_index("ix_authorized_ingestion_correlation","authorized_clinical_ingestion_records",["tenant_id","correlation_id"])
    op.execute("CREATE TRIGGER authorized_clinical_ingestion_append_only BEFORE UPDATE OR DELETE ON authorized_clinical_ingestion_records FOR EACH ROW EXECUTE FUNCTION reject_immutable_history_mutation()")
    op.execute("ALTER TABLE authorized_clinical_ingestion_records ENABLE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY authorized_clinical_ingestion_tenant_isolation ON authorized_clinical_ingestion_records USING (tenant_id = NULLIF(current_setting('jmorais.tenant_id', true), '')) WITH CHECK (tenant_id = NULLIF(current_setting('jmorais.tenant_id', true), ''))")
    op.execute("GRANT SELECT,INSERT ON authorized_clinical_ingestion_records TO jmorais_application_writer")
    op.execute("GRANT SELECT ON authorized_clinical_ingestion_records TO jmorais_application_reader")
    op.execute("GRANT USAGE,SELECT ON SEQUENCE authorized_clinical_ingestion_records_sequence_id_seq TO jmorais_application_writer")
    op.execute("REVOKE UPDATE,DELETE,TRUNCATE ON authorized_clinical_ingestion_records FROM jmorais_application_writer,jmorais_application_reader")


def downgrade():
    raise RuntimeError("authorized clinical-ingestion history cannot be destructively downgraded")
