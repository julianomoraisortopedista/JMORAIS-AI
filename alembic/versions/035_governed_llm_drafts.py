"""Create immutable tenant-scoped governed LLM drafts."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision="035_governed_llm_drafts";down_revision="034_llm_reviewable_hash";branch_labels=None;depends_on=None
def upgrade():
    op.create_table("governed_llm_drafts",
        sa.Column("sequence_id",sa.BigInteger,sa.Identity(),primary_key=True),sa.Column("draft_id",sa.String(80),nullable=False,unique=True),
        sa.Column("draft_stream_id",sa.String(96),nullable=False),sa.Column("version",sa.Integer,nullable=False),sa.Column("predecessor",sa.String(80),nullable=True),
        sa.Column("invocation_id",sa.String(80),nullable=False),sa.Column("request_id",sa.String(128),nullable=False),sa.Column("correlation_id",sa.String(128),nullable=False),
        sa.Column("tenant_id",sa.String(128),nullable=False),sa.Column("output_classification",sa.String(32),nullable=False),sa.Column("review_status",sa.String(32),nullable=False),
        sa.Column("reviewable_content_hash",sa.String(64),nullable=False),sa.Column("integrity_hash",sa.String(64),nullable=False),sa.Column("issued_at",sa.DateTime(timezone=True),nullable=False),
        sa.Column("policy_version",sa.String(64),nullable=False),sa.Column("payload",postgresql.JSONB,nullable=False),sa.Column("schema_version",sa.Integer,nullable=False),
        sa.UniqueConstraint("tenant_id","draft_stream_id","version",name="uq_governed_draft_stream_version"),
        sa.CheckConstraint("version > 0",name="ck_governed_draft_version_positive"),sa.CheckConstraint("length(reviewable_content_hash)=64",name="ck_governed_draft_content_hash"),sa.CheckConstraint("length(integrity_hash)=64",name="ck_governed_draft_integrity_hash"))
    op.create_index("ix_governed_drafts_invocation","governed_llm_drafts",["invocation_id"]);op.create_index("ix_governed_drafts_request","governed_llm_drafts",["request_id"]);op.create_index("ix_governed_drafts_tenant","governed_llm_drafts",["tenant_id"])
    op.execute("CREATE TRIGGER governed_llm_drafts_append_only BEFORE UPDATE OR DELETE ON governed_llm_drafts FOR EACH ROW EXECUTE FUNCTION reject_immutable_history_mutation()")
    op.execute("ALTER TABLE governed_llm_drafts ENABLE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY governed_llm_drafts_tenant_isolation ON governed_llm_drafts USING (tenant_id = NULLIF(current_setting('jmorais.tenant_id', true), '')) WITH CHECK (tenant_id = NULLIF(current_setting('jmorais.tenant_id', true), ''))")
    op.execute("GRANT SELECT,INSERT ON governed_llm_drafts TO jmorais_application_writer");op.execute("GRANT SELECT ON governed_llm_drafts TO jmorais_application_reader");op.execute("GRANT USAGE,SELECT ON SEQUENCE governed_llm_drafts_sequence_id_seq TO jmorais_application_writer");op.execute("REVOKE UPDATE,DELETE,TRUNCATE ON governed_llm_drafts FROM jmorais_application_writer,jmorais_application_reader")
def downgrade():raise RuntimeError("governed LLM draft history cannot be destructively downgraded")
