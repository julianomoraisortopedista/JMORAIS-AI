"""Append-only governed guideline recommendations.

Revision ID: 015_guideline_recs
Revises: 014_terminology
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision="015_guideline_recs";down_revision="014_terminology";branch_labels=None;depends_on=None
def upgrade():
    op.create_table("guideline_recommendation_versions",sa.Column("set_id",sa.String(67),primary_key=True),sa.Column("subject_reference",sa.String(67),nullable=False),sa.Column("set_version",sa.Integer,nullable=False),sa.Column("previous_set_id",sa.String(67),sa.ForeignKey("guideline_recommendation_versions.set_id",ondelete="RESTRICT")),sa.Column("reasoning_input_id",sa.String(67),nullable=False),sa.Column("readiness",sa.String(32),nullable=False),sa.Column("review_status",sa.String(32),nullable=False),sa.Column("policy_version",sa.String(64),nullable=False),sa.Column("generated_at",sa.DateTime(timezone=True),nullable=False),sa.Column("payload",postgresql.JSONB,nullable=False),sa.Column("schema_version",sa.Integer,nullable=False),sa.UniqueConstraint("subject_reference","set_version",name="uq_guideline_rec_subject_version"),sa.CheckConstraint("set_version > 0","ck_guideline_rec_version_positive"))
    op.create_table("guideline_recommendation_audit",sa.Column("sequence_id",sa.BigInteger,sa.Identity(),primary_key=True),sa.Column("event_id",sa.String(67),nullable=False,unique=True),sa.Column("subject_reference",sa.String(67),nullable=False),sa.Column("set_id",sa.String(67),nullable=False),sa.Column("event_type",sa.String(32),nullable=False),sa.Column("occurred_at",sa.DateTime(timezone=True),nullable=False),sa.Column("actor_id",sa.String(128),nullable=False),sa.Column("decision_code",sa.String(64),nullable=False),sa.Column("reference_ids",postgresql.JSONB,nullable=False),sa.Column("policy_version",sa.String(64),nullable=False))
    for table in ("guideline_recommendation_versions","guideline_recommendation_audit"):op.execute(f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION reject_immutable_history_mutation()")
def downgrade():raise RuntimeError("guideline recommendation history cannot be destructively downgraded")
