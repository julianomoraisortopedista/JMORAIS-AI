"""Patient Context immutable version stream.

Revision ID: 009_patient_context
Revises: 008_reviewer_identity
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision="009_patient_context";down_revision="008_reviewer_identity";branch_labels=None;depends_on=None

def upgrade():
    op.create_table("patient_context_versions",
      sa.Column("context_id",sa.String(64),primary_key=True),sa.Column("patient_id",sa.String(64),nullable=False),
      sa.Column("version",sa.Integer,nullable=False),sa.Column("previous_context_id",sa.String(64),sa.ForeignKey("patient_context_versions.context_id",ondelete="RESTRICT")),
      sa.Column("effective_at",sa.DateTime(timezone=True),nullable=False),sa.Column("payload",postgresql.JSONB,nullable=False),
      sa.Column("schema_version",sa.Integer,nullable=False),sa.UniqueConstraint("patient_id","version",name="uq_patient_context_patient_version"),
      sa.CheckConstraint("version > 0",name="ck_patient_context_version_positive"))
    op.create_index("ix_patient_context_patient_version","patient_context_versions",["patient_id","version"])
    op.execute("""CREATE TRIGGER patient_context_versions_append_only BEFORE UPDATE OR DELETE ON patient_context_versions
      FOR EACH ROW EXECUTE FUNCTION reject_immutable_history_mutation()""")

def downgrade(): raise RuntimeError("patient context history cannot be destructively downgraded")
