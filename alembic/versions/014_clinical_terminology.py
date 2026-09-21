"""Append-only canonical clinical terminology.

Revision ID: 014_terminology
Revises: 013_reasoning_input
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision="014_terminology";down_revision="013_reasoning_input";branch_labels=None;depends_on=None
def upgrade():
    op.create_table("terminology_records",
      sa.Column("sequence_id",sa.BigInteger,sa.Identity(),primary_key=True),sa.Column("stream_id",sa.String(128),nullable=False),
      sa.Column("stream_position",sa.Integer,nullable=False),sa.Column("record_type",sa.String(64),nullable=False),
      sa.Column("code_system",sa.String(40),nullable=False),sa.Column("terminology_version",sa.String(64),nullable=False),
      sa.Column("payload",postgresql.JSONB,nullable=False),sa.Column("schema_version",sa.Integer,nullable=False),
      sa.UniqueConstraint("stream_id","stream_position",name="uq_terminology_stream_position"),sa.CheckConstraint("stream_position > 0","ck_terminology_position_positive"))
    op.create_index("ix_terminology_system_version","terminology_records",["code_system","terminology_version"])
    op.create_table("terminology_audit_events",
      sa.Column("sequence_id",sa.BigInteger,sa.Identity(),primary_key=True),sa.Column("event_id",sa.String(67),nullable=False,unique=True),
      sa.Column("event_type",sa.String(32),nullable=False),sa.Column("subject_reference",sa.String(256),nullable=False),
      sa.Column("occurred_at",sa.DateTime(timezone=True),nullable=False),sa.Column("actor_id",sa.String(128),nullable=False),
      sa.Column("version_reference",sa.String(64),nullable=False),sa.Column("outcome",sa.String(32),nullable=False),sa.Column("provenance",sa.String(512),nullable=False))
    for table in ("terminology_records","terminology_audit_events"):
        op.execute(f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION reject_immutable_history_mutation()")
def downgrade():raise RuntimeError("terminology history cannot be destructively downgraded")
