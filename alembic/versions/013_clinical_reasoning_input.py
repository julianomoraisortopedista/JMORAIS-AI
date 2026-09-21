"""Append-only Clinical Reasoning Input contract.

Revision ID: 013_reasoning_input
Revises: 012_clinical_state
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision="013_reasoning_input";down_revision="012_clinical_state";branch_labels=None;depends_on=None
def upgrade():
    op.create_table("clinical_reasoning_input_versions",
      sa.Column("input_id",sa.String(67),primary_key=True),sa.Column("subject_reference",sa.String(67),nullable=False),
      sa.Column("input_version",sa.Integer,nullable=False),sa.Column("previous_input_id",sa.String(67),sa.ForeignKey("clinical_reasoning_input_versions.input_id",ondelete="RESTRICT")),
      sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),sa.Column("review_status",sa.String(32),nullable=False),sa.Column("readiness",sa.String(32),nullable=False),
      sa.Column("payload",postgresql.JSONB,nullable=False),sa.Column("schema_version",sa.Integer,nullable=False),
      sa.UniqueConstraint("subject_reference","input_version",name="uq_reasoning_input_subject_version"),sa.CheckConstraint("input_version > 0","ck_reasoning_input_version_positive"))
    op.create_table("clinical_reasoning_input_audit",
      sa.Column("sequence_id",sa.BigInteger,sa.Identity(),primary_key=True),sa.Column("event_id",sa.String(67),nullable=False,unique=True),
      sa.Column("subject_reference",sa.String(67),nullable=False),sa.Column("input_id",sa.String(67),nullable=False),sa.Column("event_type",sa.String(32),nullable=False),
      sa.Column("occurred_at",sa.DateTime(timezone=True),nullable=False),sa.Column("actor_id",sa.String(128),nullable=False),
      sa.Column("source_reference",sa.String(128),nullable=False),sa.Column("policy_version",sa.String(64),nullable=False),sa.Column("decision_code",sa.String(64),nullable=False))
    for table in ("clinical_reasoning_input_versions","clinical_reasoning_input_audit"):
        op.execute(f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION reject_immutable_history_mutation()")
def downgrade():raise RuntimeError("reasoning-input history cannot be destructively downgraded")
