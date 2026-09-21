"""Owner-issued exact persisted GovernedLLMDraft references."""

from alembic import op
import sqlalchemy as sa


revision = "054_governed_llm_draft_exact_ref"
down_revision = "053_governed_evidence_exact_ref"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "governed_llm_draft_persisted_references",
        sa.Column("sequence_id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("reference_id", sa.String(68), nullable=False, unique=True),
        sa.Column("draft_id", sa.String(80), nullable=False),
        sa.Column("draft_stream_id", sa.String(96), nullable=False),
        sa.Column("draft_version", sa.Integer, nullable=False),
        sa.Column("predecessor", sa.String(80)),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("invocation_id", sa.String(80), nullable=False),
        sa.Column("request_id", sa.String(128), nullable=False),
        sa.Column("correlation_id", sa.String(128), nullable=False),
        sa.Column("persisted_gateway_input_id", sa.String(68), nullable=False),
        sa.Column("upstream_artifact_type", sa.String(64), nullable=False),
        sa.Column("upstream_artifact_id", sa.String(160), nullable=False),
        sa.Column("upstream_artifact_version", sa.Integer, nullable=False),
        sa.Column("upstream_integrity_reference", sa.String(128), nullable=False),
        sa.Column("upstream_policy_version", sa.String(128), nullable=False),
        sa.Column("upstream_source_context", sa.String(64), nullable=False),
        sa.Column("policy_version", sa.String(128), nullable=False),
        sa.Column("lifecycle_event_id", sa.String(96), nullable=False),
        sa.Column("lifecycle_status", sa.String(20), nullable=False),
        sa.Column("lifecycle_integrity_hash", sa.String(64), nullable=False),
        sa.Column("reviewable_content_hash", sa.String(64), nullable=False),
        sa.Column("draft_integrity_hash", sa.String(64), nullable=False),
        sa.Column("provenance_reference", sa.String(128), nullable=False),
        sa.Column("integrity_hash", sa.String(64), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "draft_id", "draft_version", name="uq_governed_draft_exact_reference"),
        sa.CheckConstraint("draft_version > 0 AND upstream_artifact_version > 0", name="ck_governed_draft_reference_versions"),
        sa.CheckConstraint("lifecycle_status='ACTIVE'", name="ck_governed_draft_reference_active"),
        sa.CheckConstraint("length(lifecycle_integrity_hash)=64 AND length(reviewable_content_hash)=64 AND length(draft_integrity_hash)=64 AND length(integrity_hash)=64", name="ck_governed_draft_reference_hashes"),
    )
    op.create_index(
        "ix_governed_draft_reference_exact",
        "governed_llm_draft_persisted_references",
        ["tenant_id", "reference_id", "draft_id", "draft_version"],
    )
    op.execute("CREATE TRIGGER governed_llm_draft_persisted_references_append_only BEFORE UPDATE OR DELETE ON governed_llm_draft_persisted_references FOR EACH ROW EXECUTE FUNCTION reject_immutable_history_mutation()")
    op.execute("ALTER TABLE governed_llm_draft_persisted_references ENABLE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY governed_llm_draft_persisted_references_tenant_isolation ON governed_llm_draft_persisted_references USING (tenant_id=NULLIF(current_setting('jmorais.tenant_id',true),'')) WITH CHECK (tenant_id=NULLIF(current_setting('jmorais.tenant_id',true),''))")
    op.execute("GRANT SELECT,INSERT ON governed_llm_draft_persisted_references TO jmorais_application_writer")
    op.execute("GRANT SELECT ON governed_llm_draft_persisted_references TO jmorais_application_reader")
    op.execute("GRANT USAGE,SELECT ON SEQUENCE governed_llm_draft_persisted_references_sequence_id_seq TO jmorais_application_writer")
    op.execute("REVOKE UPDATE,DELETE,TRUNCATE ON governed_llm_draft_persisted_references FROM jmorais_application_writer,jmorais_application_reader")
    op.execute("GRANT SELECT ON governed_llm_draft_persisted_references TO jmorais_offline_replay_verifier")
    op.execute("REVOKE INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER ON governed_llm_draft_persisted_references FROM jmorais_offline_replay_verifier")
    op.execute("""CREATE FUNCTION checkpoint_governed_llm_draft_reference() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$ BEGIN INSERT INTO cryptographic_stream_checkpoints(stream_namespace,stream_id,stream_position,head_hash,recorded_at) VALUES('governed_llm_draft_persisted_references',NEW.tenant_id||'|'||NEW.reference_id,1,NEW.integrity_hash,NEW.issued_at);RETURN NEW;END;$$""")
    op.execute("CREATE TRIGGER governed_llm_draft_persisted_references_checkpoint AFTER INSERT ON governed_llm_draft_persisted_references FOR EACH ROW EXECUTE FUNCTION checkpoint_governed_llm_draft_reference()")


def downgrade():
    raise RuntimeError("exact governed draft references cannot be destructively downgraded")
