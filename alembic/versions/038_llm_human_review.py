"""Create tenant-scoped immutable LLM human review event streams."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "038_llm_human_review"
down_revision = "037_backfill_draft_lifecycle"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("llm_human_review_events",
        sa.Column("sequence_id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("review_event_id", sa.String(96), nullable=False, unique=True),
        sa.Column("draft_id", sa.String(80), sa.ForeignKey("governed_llm_drafts.draft_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("draft_version", sa.Integer, nullable=False), sa.Column("invocation_id", sa.String(96), nullable=False),
        sa.Column("request_id", sa.String(128), nullable=False), sa.Column("correlation_id", sa.String(128), nullable=False),
        sa.Column("tenant_id", sa.String(128), nullable=False), sa.Column("organization_id", sa.String(128), nullable=False),
        sa.Column("prior_state", sa.String(40), nullable=False), sa.Column("resulting_state", sa.String(40), nullable=False),
        sa.Column("decision", sa.String(32), nullable=False), sa.Column("reviewer_id", sa.String(128), nullable=False),
        sa.Column("reviewer_role", sa.String(40), nullable=False), sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False), sa.Column("stream_position", sa.Integer, nullable=False),
        sa.Column("predecessor_event_id", sa.String(96)), sa.Column("previous_hash", sa.String(64)),
        sa.Column("integrity_hash", sa.String(64), nullable=False), sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column("schema_version", sa.Integer, nullable=False),
        sa.UniqueConstraint("tenant_id", "draft_id", "stream_position", name="uq_llm_human_review_position"),
        sa.CheckConstraint("stream_position > 0", name="ck_llm_human_review_position"),
        sa.CheckConstraint("length(integrity_hash)=64", name="ck_llm_human_review_integrity_hash"))
    op.create_index("ix_llm_human_review_tenant", "llm_human_review_events", ["tenant_id"])
    op.create_index("ix_llm_human_review_invocation", "llm_human_review_events", ["invocation_id"])
    op.create_index("ix_llm_human_review_correlation", "llm_human_review_events", ["correlation_id"])
    op.execute("CREATE TRIGGER llm_human_review_append_only BEFORE UPDATE OR DELETE ON llm_human_review_events FOR EACH ROW EXECUTE FUNCTION reject_immutable_history_mutation()")
    op.execute("ALTER TABLE llm_human_review_events ENABLE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY llm_human_review_tenant_isolation ON llm_human_review_events USING (tenant_id = NULLIF(current_setting('jmorais.tenant_id', true), '')) WITH CHECK (tenant_id = NULLIF(current_setting('jmorais.tenant_id', true), ''))")
    op.execute("GRANT SELECT,INSERT ON llm_human_review_events TO jmorais_application_writer")
    op.execute("GRANT SELECT ON llm_human_review_events TO jmorais_application_reader")
    op.execute("GRANT USAGE,SELECT ON SEQUENCE llm_human_review_events_sequence_id_seq TO jmorais_application_writer")
    op.execute("REVOKE UPDATE,DELETE,TRUNCATE ON llm_human_review_events FROM jmorais_application_writer,jmorais_application_reader")


def downgrade():
    raise RuntimeError("LLM human review history cannot be destructively downgraded")
