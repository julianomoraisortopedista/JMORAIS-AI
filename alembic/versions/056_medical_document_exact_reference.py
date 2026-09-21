"""Medical Documents owner-issued exact version references."""
from alembic import op
import sqlalchemy as sa

revision="056_medical_document_exact_ref"
down_revision="055_llm_invocation_exact_ref"
branch_labels=None
depends_on=None

def upgrade():
    op.create_table("medical_document_persisted_references",
        sa.Column("sequence_id",sa.BigInteger,sa.Identity(),primary_key=True),
        sa.Column("reference_id",sa.String(68),nullable=False,unique=True),
        sa.Column("document_stream_id",sa.String(68),nullable=False),sa.Column("document_id",sa.String(68),nullable=False),
        sa.Column("version_id",sa.String(68),nullable=False),sa.Column("document_version",sa.Integer,nullable=False),
        sa.Column("predecessor",sa.String(68)),sa.Column("tenant_id",sa.String(128),nullable=False),
        sa.Column("policy_version",sa.Text,nullable=False),sa.Column("document_type",sa.String(48),nullable=False),
        sa.Column("validation_status",sa.String(8),nullable=False),sa.Column("review_status",sa.String(32),nullable=False),
        sa.Column("document_integrity_hash",sa.String(64),nullable=False),sa.Column("provenance_reference",sa.String(128),nullable=False),
        sa.Column("reasoning_input_id",sa.String(80),nullable=False),sa.Column("reasoning_input_version",sa.Integer,nullable=False),
        sa.Column("clinical_state_reference_id",sa.String(96),nullable=False),sa.Column("clinical_state_version",sa.Integer,nullable=False),
        sa.Column("guideline_reference_id",sa.String(68)),sa.Column("orthopedic_reference_id",sa.String(68)),
        sa.Column("traceability_hash",sa.String(64),nullable=False),sa.Column("integrity_hash",sa.String(64),nullable=False),
        sa.Column("issued_at",sa.DateTime(timezone=True),nullable=False),
        sa.UniqueConstraint("tenant_id","version_id",name="uq_medical_document_exact_reference"),
        sa.CheckConstraint("document_version>0 AND reasoning_input_version>0 AND clinical_state_version>0",name="ck_medical_document_reference_versions"),
        sa.CheckConstraint("length(document_integrity_hash)=64 AND length(traceability_hash)=64 AND length(integrity_hash)=64",name="ck_medical_document_reference_hashes"))
    op.create_index("ix_medical_document_reference_exact","medical_document_persisted_references",["tenant_id","reference_id","version_id"])
    op.execute("CREATE TRIGGER medical_document_persisted_references_append_only BEFORE UPDATE OR DELETE ON medical_document_persisted_references FOR EACH ROW EXECUTE FUNCTION reject_immutable_history_mutation()")
    op.execute("ALTER TABLE medical_document_persisted_references ENABLE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY medical_document_persisted_references_tenant_isolation ON medical_document_persisted_references USING (tenant_id=NULLIF(current_setting('jmorais.tenant_id',true),'')) WITH CHECK (tenant_id=NULLIF(current_setting('jmorais.tenant_id',true),''))")
    op.execute("GRANT SELECT,INSERT ON medical_document_persisted_references TO jmorais_application_writer")
    op.execute("GRANT SELECT ON medical_document_persisted_references TO jmorais_application_reader")
    op.execute("GRANT USAGE,SELECT ON SEQUENCE medical_document_persisted_references_sequence_id_seq TO jmorais_application_writer")
    op.execute("REVOKE UPDATE,DELETE,TRUNCATE ON medical_document_persisted_references FROM jmorais_application_writer,jmorais_application_reader")
    op.execute("GRANT SELECT ON medical_document_persisted_references TO jmorais_offline_replay_verifier")
    op.execute("REVOKE INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER ON medical_document_persisted_references FROM jmorais_offline_replay_verifier")
    op.execute("""CREATE FUNCTION checkpoint_medical_document_reference() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$ BEGIN INSERT INTO cryptographic_stream_checkpoints(stream_namespace,stream_id,stream_position,head_hash,recorded_at) VALUES('medical_document_persisted_references',NEW.tenant_id||'|'||NEW.reference_id,1,NEW.integrity_hash,NEW.issued_at);RETURN NEW;END;$$""")
    op.execute("CREATE TRIGGER medical_document_persisted_references_checkpoint AFTER INSERT ON medical_document_persisted_references FOR EACH ROW EXECUTE FUNCTION checkpoint_medical_document_reference()")

def downgrade(): raise RuntimeError("exact medical document references cannot be destructively downgraded")
