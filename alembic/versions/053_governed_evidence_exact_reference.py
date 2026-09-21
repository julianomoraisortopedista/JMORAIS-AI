"""Owner-issued exact persisted GovernedEvidence references."""
from alembic import op
import sqlalchemy as sa
revision="053_governed_evidence_exact_ref";down_revision="052_clinical_state_exact_refs";branch_labels=None;depends_on=None

def upgrade():
    op.create_table("governed_evidence_persisted_references",
      sa.Column("sequence_id",sa.BigInteger,sa.Identity(),primary_key=True),
      sa.Column("reference_id",sa.String(68),nullable=False,unique=True),
      sa.Column("governed_evidence_id",sa.String(64),nullable=False),
      sa.Column("stream_version",sa.Integer,nullable=False),sa.Column("tenant_id",sa.String(128),nullable=False),
      sa.Column("evidence_package_id",sa.String(64),nullable=False),
      sa.Column("appraisal_record_id",sa.String(80),nullable=False),
      sa.Column("appraisal_record_version",sa.Integer,nullable=False),sa.Column("policy_version",sa.String(128),nullable=False),
      sa.Column("lifecycle_event_id",sa.String(64),nullable=False),
      sa.Column("lifecycle_status",sa.String(32),nullable=False),sa.Column("lifecycle_integrity_hash",sa.String(64),nullable=False),
      sa.Column("provenance_reference",sa.String(128),nullable=False),sa.Column("governed_evidence_integrity_hash",sa.String(64),nullable=False),
      sa.Column("integrity_hash",sa.String(64),nullable=False),sa.Column("issued_at",sa.DateTime(timezone=True),nullable=False),
      sa.UniqueConstraint("tenant_id","governed_evidence_id","stream_version",name="uq_governed_evidence_exact_reference"),
      sa.CheckConstraint("stream_version>0 AND appraisal_record_version>0",name="ck_governed_evidence_reference_versions"),
      sa.CheckConstraint("lifecycle_status='ACTIVE'",name="ck_governed_evidence_reference_active"),
      sa.CheckConstraint("length(lifecycle_integrity_hash)=64 AND length(governed_evidence_integrity_hash)=64 AND length(integrity_hash)=64",name="ck_governed_evidence_reference_hashes"))
    op.create_index("ix_governed_evidence_reference_exact","governed_evidence_persisted_references",["tenant_id","reference_id","governed_evidence_id","stream_version"])
    op.execute("CREATE TRIGGER governed_evidence_persisted_references_append_only BEFORE UPDATE OR DELETE ON governed_evidence_persisted_references FOR EACH ROW EXECUTE FUNCTION reject_immutable_history_mutation()")
    op.execute("ALTER TABLE governed_evidence_persisted_references ENABLE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY governed_evidence_persisted_references_tenant_isolation ON governed_evidence_persisted_references USING (tenant_id=NULLIF(current_setting('jmorais.tenant_id',true),'')) WITH CHECK (tenant_id=NULLIF(current_setting('jmorais.tenant_id',true),''))")
    op.execute("GRANT SELECT,INSERT ON governed_evidence_persisted_references TO jmorais_application_writer")
    op.execute("GRANT SELECT ON governed_evidence_persisted_references TO jmorais_application_reader")
    op.execute("GRANT USAGE,SELECT ON SEQUENCE governed_evidence_persisted_references_sequence_id_seq TO jmorais_application_writer")
    op.execute("REVOKE UPDATE,DELETE,TRUNCATE ON governed_evidence_persisted_references FROM jmorais_application_writer,jmorais_application_reader")
    op.execute("GRANT SELECT ON governed_evidence_persisted_references TO jmorais_offline_replay_verifier")
    op.execute("REVOKE INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER ON governed_evidence_persisted_references FROM jmorais_offline_replay_verifier")
    op.execute("""CREATE FUNCTION checkpoint_governed_evidence_reference() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$ BEGIN INSERT INTO cryptographic_stream_checkpoints(stream_namespace,stream_id,stream_position,head_hash,recorded_at) VALUES('governed_evidence_persisted_references',NEW.tenant_id||'|'||NEW.reference_id,1,NEW.integrity_hash,NEW.issued_at);RETURN NEW;END;$$""")
    op.execute("CREATE TRIGGER governed_evidence_persisted_references_checkpoint AFTER INSERT ON governed_evidence_persisted_references FOR EACH ROW EXECUTE FUNCTION checkpoint_governed_evidence_reference()")
def downgrade():raise RuntimeError("exact GovernedEvidence references cannot be destructively downgraded")
