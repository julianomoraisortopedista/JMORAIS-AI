"""Gateway-owned exact LLM invocation references and draft linkage."""

from alembic import op
import sqlalchemy as sa


revision = "055_llm_invocation_exact_ref"
down_revision = "054_governed_llm_draft_exact_ref"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "llm_invocation_persisted_references",
        sa.Column("sequence_id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("reference_id", sa.String(68), nullable=False, unique=True),
        sa.Column("invocation_id", sa.String(80), nullable=False),
        sa.Column("request_id", sa.String(128), nullable=False),
        sa.Column("correlation_id", sa.String(128), nullable=False),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("principal_id", sa.String(160), nullable=False),
        sa.Column("purpose", sa.String(96), nullable=False),
        sa.Column("prompt_version_id", sa.String(128), nullable=False),
        sa.Column("prompt_template_id", sa.String(128), nullable=False),
        sa.Column("prompt_version", sa.Integer, nullable=False),
        sa.Column("prompt_hash", sa.String(64), nullable=False),
        sa.Column("persisted_gateway_input_id", sa.String(68), nullable=False),
        sa.Column("upstream_artifact_type", sa.String(64), nullable=False),
        sa.Column("upstream_artifact_id", sa.String(160), nullable=False),
        sa.Column("upstream_artifact_version", sa.Integer, nullable=False),
        sa.Column("upstream_integrity_reference", sa.String(128), nullable=False),
        sa.Column("upstream_policy_version", sa.String(128), nullable=False),
        sa.Column("upstream_source_context", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("model_id", sa.String(160), nullable=False),
        sa.Column("policy_version", sa.String(128), nullable=False),
        sa.Column("output_classification", sa.String(32), nullable=False),
        sa.Column("invocation_status", sa.String(24), nullable=False),
        sa.Column("temperature", sa.Float, nullable=False),
        sa.Column("seed", sa.Integer),
        sa.Column("invocation_integrity_hash", sa.String(64), nullable=False),
        sa.Column("integrity_hash", sa.String(64), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "invocation_id", name="uq_llm_invocation_exact_reference"),
        sa.CheckConstraint("prompt_version > 0 AND upstream_artifact_version > 0", name="ck_llm_invocation_reference_versions"),
        sa.CheckConstraint("length(prompt_hash)=64 AND length(invocation_integrity_hash)=64 AND length(integrity_hash)=64", name="ck_llm_invocation_reference_hashes"),
    )
    op.create_index("ix_llm_invocation_reference_exact", "llm_invocation_persisted_references", ["tenant_id", "reference_id", "invocation_id"])
    op.execute("CREATE TRIGGER llm_invocation_persisted_references_append_only BEFORE UPDATE OR DELETE ON llm_invocation_persisted_references FOR EACH ROW EXECUTE FUNCTION reject_immutable_history_mutation()")
    op.execute("ALTER TABLE llm_invocation_persisted_references ENABLE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY llm_invocation_persisted_references_tenant_isolation ON llm_invocation_persisted_references USING (tenant_id=NULLIF(current_setting('jmorais.tenant_id',true),'')) WITH CHECK (tenant_id=NULLIF(current_setting('jmorais.tenant_id',true),''))")
    op.execute("GRANT SELECT,INSERT ON llm_invocation_persisted_references TO jmorais_application_writer")
    op.execute("GRANT SELECT ON llm_invocation_persisted_references TO jmorais_application_reader")
    op.execute("GRANT USAGE,SELECT ON SEQUENCE llm_invocation_persisted_references_sequence_id_seq TO jmorais_application_writer")
    op.execute("REVOKE UPDATE,DELETE,TRUNCATE ON llm_invocation_persisted_references FROM jmorais_application_writer,jmorais_application_reader")
    op.execute("GRANT SELECT ON llm_invocation_persisted_references TO jmorais_offline_replay_verifier")
    op.execute("REVOKE INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER ON llm_invocation_persisted_references FROM jmorais_offline_replay_verifier")
    op.execute("""CREATE FUNCTION checkpoint_llm_invocation_reference() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$ BEGIN INSERT INTO cryptographic_stream_checkpoints(stream_namespace,stream_id,stream_position,head_hash,recorded_at) VALUES('llm_invocation_persisted_references',NEW.tenant_id||'|'||NEW.reference_id,1,NEW.integrity_hash,NEW.issued_at);RETURN NEW;END;$$""")
    op.execute("CREATE TRIGGER llm_invocation_persisted_references_checkpoint AFTER INSERT ON llm_invocation_persisted_references FOR EACH ROW EXECUTE FUNCTION checkpoint_llm_invocation_reference()")
    op.add_column("governed_llm_draft_persisted_references", sa.Column("invocation_reference_id", sa.String(68)))
    op.add_column("governed_llm_draft_persisted_references", sa.Column("invocation_reference_integrity_hash", sa.String(64)))
    op.create_index("ix_governed_draft_invocation_reference", "governed_llm_draft_persisted_references", ["tenant_id", "invocation_reference_id"])


def downgrade():
    raise RuntimeError("exact invocation references cannot be destructively downgraded")
