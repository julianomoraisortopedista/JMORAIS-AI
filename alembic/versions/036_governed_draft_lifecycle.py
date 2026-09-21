"""Create immutable hash-linked governed draft lifecycle."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision="036_draft_lifecycle";down_revision="035_governed_llm_drafts";branch_labels=None;depends_on=None
def upgrade():
    op.create_table("governed_llm_draft_lifecycle_events",
        sa.Column("sequence_id",sa.BigInteger,sa.Identity(),primary_key=True),sa.Column("lifecycle_event_id",sa.String(96),nullable=False,unique=True),
        sa.Column("draft_id",sa.String(80),sa.ForeignKey("governed_llm_drafts.draft_id",ondelete="RESTRICT"),nullable=False),sa.Column("draft_version",sa.Integer,nullable=False),
        sa.Column("tenant_id",sa.String(128),nullable=False),sa.Column("stream_position",sa.Integer,nullable=False),sa.Column("prior_status",sa.String(20),nullable=True),sa.Column("resulting_status",sa.String(20),nullable=False),
        sa.Column("reason_reference",sa.String(256),nullable=False),sa.Column("actor_reference",sa.String(160),nullable=False),sa.Column("policy_version",sa.String(64),nullable=False),sa.Column("occurred_at",sa.DateTime(timezone=True),nullable=False),
        sa.Column("predecessor_event_id",sa.String(96),nullable=True),sa.Column("previous_hash",sa.String(64),nullable=True),sa.Column("integrity_hash",sa.String(64),nullable=False),sa.Column("payload",postgresql.JSONB,nullable=False),sa.Column("schema_version",sa.Integer,nullable=False),
        sa.UniqueConstraint("tenant_id","draft_id","stream_position",name="uq_draft_lifecycle_position"),sa.CheckConstraint("stream_position > 0",name="ck_draft_lifecycle_position"),
        sa.CheckConstraint("resulting_status IN ('ACTIVE','SUPERSEDED','INVALIDATED')",name="ck_draft_lifecycle_status"),sa.CheckConstraint("prior_status IS NULL OR prior_status IN ('ACTIVE','SUPERSEDED','INVALIDATED')",name="ck_draft_lifecycle_prior"),sa.CheckConstraint("length(integrity_hash)=64",name="ck_draft_lifecycle_hash"))
    op.create_index("ix_draft_lifecycle_tenant","governed_llm_draft_lifecycle_events",["tenant_id"]);op.create_index("ix_draft_lifecycle_draft","governed_llm_draft_lifecycle_events",["draft_id"])
    op.execute("CREATE TRIGGER governed_llm_draft_lifecycle_append_only BEFORE UPDATE OR DELETE ON governed_llm_draft_lifecycle_events FOR EACH ROW EXECUTE FUNCTION reject_immutable_history_mutation()")
    op.execute("ALTER TABLE governed_llm_draft_lifecycle_events ENABLE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY governed_llm_draft_lifecycle_tenant_isolation ON governed_llm_draft_lifecycle_events USING (tenant_id = NULLIF(current_setting('jmorais.tenant_id', true), '')) WITH CHECK (tenant_id = NULLIF(current_setting('jmorais.tenant_id', true), ''))")
    op.execute("GRANT SELECT,INSERT ON governed_llm_draft_lifecycle_events TO jmorais_application_writer");op.execute("GRANT SELECT ON governed_llm_draft_lifecycle_events TO jmorais_application_reader");op.execute("GRANT USAGE,SELECT ON SEQUENCE governed_llm_draft_lifecycle_events_sequence_id_seq TO jmorais_application_writer");op.execute("REVOKE UPDATE,DELETE,TRUNCATE ON governed_llm_draft_lifecycle_events FROM jmorais_application_writer,jmorais_application_reader")
def downgrade():raise RuntimeError("governed draft lifecycle cannot be destructively downgraded")
