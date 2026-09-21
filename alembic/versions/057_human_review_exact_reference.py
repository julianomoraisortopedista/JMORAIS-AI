"""Human Review owner-issued exact event references."""
from alembic import op
import sqlalchemy as sa
revision="057_human_review_exact_ref";down_revision="056_medical_document_exact_ref";branch_labels=None;depends_on=None
def upgrade():
    op.create_table("human_review_persisted_references",
        sa.Column("sequence_id",sa.BigInteger,sa.Identity(),primary_key=True),sa.Column("reference_id",sa.String(68),nullable=False,unique=True),
        sa.Column("review_event_id",sa.String(80),nullable=False),sa.Column("draft_reference_id",sa.String(68),nullable=False),
        sa.Column("draft_reference_integrity_hash",sa.String(64),nullable=False),sa.Column("stream_position",sa.Integer,nullable=False),
        sa.Column("tenant_id",sa.String(128),nullable=False),sa.Column("reviewer_id",sa.String(128),nullable=False),
        sa.Column("reviewer_role",sa.String(32),nullable=False),sa.Column("decision",sa.String(32),nullable=False),
        sa.Column("resulting_state",sa.String(32),nullable=False),sa.Column("policy_version",sa.String(64),nullable=False),
        sa.Column("request_id",sa.String(128),nullable=False),sa.Column("correlation_id",sa.String(128),nullable=False),
        sa.Column("predecessor_event_id",sa.String(80)),sa.Column("previous_hash",sa.String(64)),
        sa.Column("event_integrity_hash",sa.String(64),nullable=False),sa.Column("integrity_hash",sa.String(64),nullable=False),
        sa.Column("issued_at",sa.DateTime(timezone=True),nullable=False),
        sa.UniqueConstraint("tenant_id","review_event_id",name="uq_human_review_exact_reference"),
        sa.CheckConstraint("stream_position>0",name="ck_human_review_reference_position"),
        sa.CheckConstraint("length(draft_reference_integrity_hash)=64 AND length(event_integrity_hash)=64 AND length(integrity_hash)=64",name="ck_human_review_reference_hashes"))
    op.create_index("ix_human_review_reference_exact","human_review_persisted_references",["tenant_id","reference_id","review_event_id"])
    op.execute("CREATE TRIGGER human_review_persisted_references_append_only BEFORE UPDATE OR DELETE ON human_review_persisted_references FOR EACH ROW EXECUTE FUNCTION reject_immutable_history_mutation()")
    op.execute("ALTER TABLE human_review_persisted_references ENABLE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY human_review_persisted_references_tenant_isolation ON human_review_persisted_references USING (tenant_id=NULLIF(current_setting('jmorais.tenant_id',true),'')) WITH CHECK (tenant_id=NULLIF(current_setting('jmorais.tenant_id',true),''))")
    op.execute("GRANT SELECT,INSERT ON human_review_persisted_references TO jmorais_application_writer");op.execute("GRANT SELECT ON human_review_persisted_references TO jmorais_application_reader")
    op.execute("GRANT USAGE,SELECT ON SEQUENCE human_review_persisted_references_sequence_id_seq TO jmorais_application_writer")
    op.execute("REVOKE UPDATE,DELETE,TRUNCATE ON human_review_persisted_references FROM jmorais_application_writer,jmorais_application_reader")
    op.execute("GRANT SELECT ON human_review_persisted_references TO jmorais_offline_replay_verifier");op.execute("REVOKE INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER ON human_review_persisted_references FROM jmorais_offline_replay_verifier")
    op.execute("""CREATE FUNCTION checkpoint_human_review_reference() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$ BEGIN INSERT INTO cryptographic_stream_checkpoints(stream_namespace,stream_id,stream_position,head_hash,recorded_at) VALUES('human_review_persisted_references',NEW.tenant_id||'|'||NEW.reference_id,1,NEW.integrity_hash,NEW.issued_at);RETURN NEW;END;$$""")
    op.execute("CREATE TRIGGER human_review_persisted_references_checkpoint AFTER INSERT ON human_review_persisted_references FOR EACH ROW EXECUTE FUNCTION checkpoint_human_review_reference()")
def downgrade():raise RuntimeError("exact human review references cannot be destructively downgraded")
