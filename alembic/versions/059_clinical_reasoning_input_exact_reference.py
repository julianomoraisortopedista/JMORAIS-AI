"""Owner-issued exact Clinical Reasoning Input references."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision="059_reasoning_input_exact_ref";down_revision="058_reasoning_exact_lineage";branch_labels=None;depends_on=None
def upgrade():
    op.create_table("clinical_reasoning_input_persisted_references",
      sa.Column("sequence_id",sa.BigInteger,sa.Identity(),primary_key=True),sa.Column("reference_id",sa.String(68),nullable=False,unique=True),
      sa.Column("input_id",sa.String(67),nullable=False),sa.Column("input_version",sa.Integer,nullable=False),sa.Column("previous_input_id",sa.String(67)),sa.Column("predecessor_reference_id",sa.String(68)),
      sa.Column("subject_reference",sa.String(128),nullable=False),sa.Column("tenant_id",sa.String(128),nullable=False),sa.Column("policy_version",sa.String(64),nullable=False),
      sa.Column("provenance_reference",sa.String(128),nullable=False),sa.Column("input_integrity_hash",sa.String(64),nullable=False),sa.Column("upstream_references",postgresql.JSONB,nullable=False),
      sa.Column("integrity_hash",sa.String(64),nullable=False),sa.Column("issued_at",sa.DateTime(timezone=True),nullable=False),
      sa.UniqueConstraint("tenant_id","input_id",name="uq_reasoning_input_exact_reference"),sa.CheckConstraint("input_version>0",name="ck_reasoning_input_exact_version"),sa.CheckConstraint("length(input_integrity_hash)=64 AND length(integrity_hash)=64",name="ck_reasoning_input_exact_hashes"))
    op.create_index("ix_reasoning_input_exact_reference","clinical_reasoning_input_persisted_references",["tenant_id","reference_id","input_id"])
    op.execute("CREATE TRIGGER clinical_reasoning_input_persisted_references_append_only BEFORE UPDATE OR DELETE ON clinical_reasoning_input_persisted_references FOR EACH ROW EXECUTE FUNCTION reject_immutable_history_mutation()")
    op.execute("ALTER TABLE clinical_reasoning_input_persisted_references ENABLE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY clinical_reasoning_input_persisted_references_tenant_isolation ON clinical_reasoning_input_persisted_references USING (tenant_id=NULLIF(current_setting('jmorais.tenant_id',true),'')) WITH CHECK (tenant_id=NULLIF(current_setting('jmorais.tenant_id',true),''))")
    op.execute("GRANT SELECT,INSERT ON clinical_reasoning_input_persisted_references TO jmorais_application_writer");op.execute("GRANT SELECT ON clinical_reasoning_input_persisted_references TO jmorais_application_reader")
    op.execute("GRANT USAGE,SELECT ON SEQUENCE clinical_reasoning_input_persisted_references_sequence_id_seq TO jmorais_application_writer")
    op.execute("REVOKE UPDATE,DELETE,TRUNCATE ON clinical_reasoning_input_persisted_references FROM jmorais_application_writer,jmorais_application_reader")
    op.execute("GRANT SELECT ON clinical_reasoning_input_persisted_references TO jmorais_offline_replay_verifier")
    op.execute("""CREATE FUNCTION checkpoint_reasoning_input_reference() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$ BEGIN INSERT INTO cryptographic_stream_checkpoints(stream_namespace,stream_id,stream_position,head_hash,recorded_at) VALUES('clinical_reasoning_input_persisted_references',NEW.tenant_id||'|'||NEW.reference_id,1,NEW.integrity_hash,NEW.issued_at);RETURN NEW;END;$$""")
    op.execute("CREATE TRIGGER clinical_reasoning_input_persisted_references_checkpoint AFTER INSERT ON clinical_reasoning_input_persisted_references FOR EACH ROW EXECUTE FUNCTION checkpoint_reasoning_input_reference()")
def downgrade():raise RuntimeError("exact reasoning references cannot be destructively downgraded")
