"""Owner-issued exact persisted PatientContext references."""
from alembic import op
import sqlalchemy as sa

revision="051_patient_context_exact_ref"
down_revision="050_offline_replay_verifier"
branch_labels=None
depends_on=None


def upgrade():
    op.create_table("patient_context_persisted_references",
        sa.Column("sequence_id",sa.BigInteger,sa.Identity(),primary_key=True),
        sa.Column("reference_id",sa.String(68),nullable=False,unique=True),
        sa.Column("context_id",sa.String(64),sa.ForeignKey("patient_context_versions.context_id",ondelete="RESTRICT"),nullable=False),
        sa.Column("context_version",sa.Integer,nullable=False),
        sa.Column("pseudonymous_patient_id",sa.String(67),nullable=False),
        sa.Column("tenant_id",sa.String(128),nullable=False),
        sa.Column("policy_version",sa.String(128),nullable=False),
        sa.Column("authorized_ingestion_record_id",sa.String(80),sa.ForeignKey("authorized_clinical_ingestion_records.ingestion_record_id",ondelete="RESTRICT"),nullable=False),
        sa.Column("context_integrity_hash",sa.String(64),nullable=False),
        sa.Column("integrity_hash",sa.String(64),nullable=False),
        sa.Column("issued_at",sa.DateTime(timezone=True),nullable=False),
        sa.UniqueConstraint("tenant_id","context_id","context_version",name="uq_patient_context_exact_reference"),
        sa.CheckConstraint("context_version > 0",name="ck_patient_context_reference_version"),
        sa.CheckConstraint("length(context_integrity_hash)=64",name="ck_patient_context_reference_context_hash"),
        sa.CheckConstraint("length(integrity_hash)=64",name="ck_patient_context_reference_integrity"))
    op.create_index("ix_patient_context_reference_exact","patient_context_persisted_references",
        ["tenant_id","reference_id","context_id","context_version"])
    op.execute("CREATE TRIGGER patient_context_persisted_references_append_only BEFORE UPDATE OR DELETE ON patient_context_persisted_references FOR EACH ROW EXECUTE FUNCTION reject_immutable_history_mutation()")
    op.execute("ALTER TABLE patient_context_persisted_references ENABLE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY patient_context_persisted_references_tenant_isolation ON patient_context_persisted_references USING (tenant_id = NULLIF(current_setting('jmorais.tenant_id', true), '')) WITH CHECK (tenant_id = NULLIF(current_setting('jmorais.tenant_id', true), ''))")
    op.execute("GRANT SELECT,INSERT ON patient_context_persisted_references TO jmorais_application_writer")
    op.execute("GRANT SELECT ON patient_context_persisted_references TO jmorais_application_reader")
    op.execute("GRANT USAGE,SELECT ON SEQUENCE patient_context_persisted_references_sequence_id_seq TO jmorais_application_writer")
    op.execute("REVOKE UPDATE,DELETE,TRUNCATE ON patient_context_persisted_references FROM jmorais_application_writer,jmorais_application_reader")


def downgrade():
    raise RuntimeError("exact PatientContext reference history cannot be destructively downgraded")
