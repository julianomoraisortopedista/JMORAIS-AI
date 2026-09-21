"""Persist trusted tenant-scoped LLM invocation context append-only."""
from alembic import op
import sqlalchemy as sa

revision="032_llm_invocation_context";down_revision="031_llm_invocation_metadata";branch_labels=None;depends_on=None

def upgrade():
    op.create_table("llm_invocation_contexts",
        sa.Column("sequence_id",sa.BigInteger,sa.Identity(),primary_key=True),
        sa.Column("request_id",sa.String(128),nullable=False),
        sa.Column("correlation_id",sa.String(128),nullable=False),
        sa.Column("tenant_id",sa.String(128),nullable=False),
        sa.Column("principal_id",sa.String(128),nullable=False),
        sa.Column("purpose",sa.String(128),nullable=False),
        sa.Column("policy_version",sa.String(64),nullable=False),
        sa.Column("issued_at",sa.DateTime(timezone=True),nullable=False),
        sa.Column("integrity_hash",sa.String(64),nullable=False),
        sa.CheckConstraint("length(trim(request_id)) > 0",name="ck_llm_context_request_nonempty"),
        sa.CheckConstraint("length(trim(correlation_id)) > 0",name="ck_llm_context_correlation_nonempty"),
        sa.CheckConstraint("length(trim(tenant_id)) > 0",name="ck_llm_context_tenant_nonempty"),
        sa.CheckConstraint("length(trim(principal_id)) > 0",name="ck_llm_context_principal_nonempty"),
        sa.CheckConstraint("length(trim(purpose)) > 0",name="ck_llm_context_purpose_nonempty"),
        sa.CheckConstraint("length(integrity_hash) = 64",name="ck_llm_context_integrity_hash"),
        sa.CheckConstraint("request_id <> correlation_id",name="ck_llm_context_distinct_identifiers"),
        sa.UniqueConstraint("tenant_id","request_id",name="uq_llm_context_tenant_request"))
    op.create_index("ix_llm_invocation_contexts_correlation_id","llm_invocation_contexts",["correlation_id"])
    op.create_index("ix_llm_invocation_contexts_tenant_id","llm_invocation_contexts",["tenant_id"])
    op.execute("CREATE TRIGGER llm_invocation_contexts_append_only BEFORE UPDATE OR DELETE ON llm_invocation_contexts FOR EACH ROW EXECUTE FUNCTION reject_immutable_history_mutation()")
    op.execute("ALTER TABLE llm_invocation_contexts ENABLE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY llm_invocation_contexts_tenant_isolation ON llm_invocation_contexts USING (tenant_id = NULLIF(current_setting('jmorais.tenant_id', true), '')) WITH CHECK (tenant_id = NULLIF(current_setting('jmorais.tenant_id', true), ''))")
    op.execute("GRANT SELECT,INSERT ON llm_invocation_contexts TO jmorais_application_writer")
    op.execute("GRANT SELECT ON llm_invocation_contexts TO jmorais_application_reader")
    op.execute("GRANT USAGE,SELECT ON SEQUENCE llm_invocation_contexts_sequence_id_seq TO jmorais_application_writer")
    op.execute("REVOKE UPDATE,DELETE,TRUNCATE ON llm_invocation_contexts FROM jmorais_application_writer,jmorais_application_reader")

def downgrade():
    raise RuntimeError("LLM invocation context history cannot be destructively downgraded")
