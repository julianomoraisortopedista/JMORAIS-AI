"""Dedicated offline replay role and metadata-only execution audit."""
from alembic import op
import sqlalchemy as sa

revision = "050_offline_replay_verifier"
down_revision = "049_e2e_manifest"
branch_labels = None
depends_on = None

REPLAY_TABLES = (
    "alembic_version",
    "canonical_ledger_claims", "canonical_ledger_supports", "canonical_ledger_events",
    "governed_clinical_audit_events", "clinical_conflict_adjudication_events",
    "governed_evidence_lifecycle_events", "governed_evidence_versions",
    "evidence_package_catalog", "evidence_package_versions", "cryptographic_stream_checkpoints",
    "persisted_gateway_inputs", "governed_llm_drafts", "governed_llm_draft_lifecycle_events",
    "llm_invocations", "llm_invocation_contexts", "llm_human_review_events",
    "llm_human_review_security_events",
)

def upgrade():
    op.execute("""DO $$ BEGIN
      IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='jmorais_offline_replay_verifier') THEN
        CREATE ROLE jmorais_offline_replay_verifier NOLOGIN BYPASSRLS;
      END IF;
      ALTER ROLE jmorais_offline_replay_verifier BYPASSRLS;
      ALTER ROLE jmorais_offline_replay_verifier SET default_transaction_read_only=on;
      EXECUTE format('GRANT jmorais_offline_replay_verifier TO %I', current_user);
    END $$""")
    op.execute("GRANT USAGE ON SCHEMA public TO jmorais_offline_replay_verifier")
    op.execute("GRANT SELECT ON " + ",".join(REPLAY_TABLES) + " TO jmorais_offline_replay_verifier")
    op.execute("REVOKE INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER ON ALL TABLES IN SCHEMA public FROM jmorais_offline_replay_verifier")
    op.create_table("offline_replay_verifier_events",
        sa.Column("sequence_id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("execution_id", sa.String(96), nullable=False, unique=True),
        sa.Column("mode", sa.String(32), nullable=False),
        sa.Column("release_id", sa.String(128), nullable=False), sa.Column("build_id", sa.String(128), nullable=False),
        sa.Column("source_revision", sa.String(128), nullable=False), sa.Column("migration_revision", sa.String(128), nullable=False),
        sa.Column("actor_id", sa.String(128), nullable=False), sa.Column("correlation_id", sa.String(128), nullable=False),
        sa.Column("verifier_role", sa.String(128), nullable=False), sa.Column("credential_provider", sa.String(128), nullable=False),
        sa.Column("credential_reference", sa.String(256), nullable=False), sa.Column("credential_version", sa.String(128)),
        sa.Column("policy_version", sa.String(64), nullable=False), sa.Column("decision", sa.String(32), nullable=False),
        sa.Column("verified_events", sa.Integer, nullable=False), sa.Column("failed_events", sa.Integer, nullable=False),
        sa.Column("broken_chains", sa.Integer, nullable=False), sa.Column("stream_count", sa.Integer, nullable=False),
        sa.Column("failure_category", sa.String(128)), sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False), sa.Column("duration_ms", sa.Float, nullable=False),
        sa.Column("disposal_status", sa.String(32), nullable=False))
    op.execute("CREATE TRIGGER offline_replay_verifier_events_append_only BEFORE UPDATE OR DELETE ON offline_replay_verifier_events FOR EACH ROW EXECUTE FUNCTION reject_immutable_history_mutation()")
    op.execute("GRANT SELECT,INSERT ON offline_replay_verifier_events TO jmorais_application_writer")
    op.execute("GRANT SELECT ON offline_replay_verifier_events TO jmorais_application_reader")
    op.execute("GRANT USAGE,SELECT ON SEQUENCE offline_replay_verifier_events_sequence_id_seq TO jmorais_application_writer")
    op.execute("REVOKE ALL ON offline_replay_verifier_events FROM jmorais_offline_replay_verifier")

def downgrade():
    raise RuntimeError("offline replay security history cannot be destructively downgraded")
