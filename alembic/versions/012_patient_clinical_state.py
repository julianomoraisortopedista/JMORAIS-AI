"""Append-only Patient Clinical State.

Revision ID: 012_clinical_state
Revises: 011_patient_id_width
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision="012_clinical_state";down_revision="011_patient_id_width";branch_labels=None;depends_on=None
def upgrade():
    op.create_table("patient_clinical_state_versions",
      sa.Column("state_id",sa.String(67),primary_key=True),sa.Column("patient_id",sa.String(67),nullable=False),
      sa.Column("patient_context_id",sa.String(64),nullable=False),sa.Column("patient_context_version",sa.Integer,nullable=False),
      sa.Column("state_version",sa.Integer,nullable=False),sa.Column("previous_state_id",sa.String(67),sa.ForeignKey("patient_clinical_state_versions.state_id",ondelete="RESTRICT")),
      sa.Column("as_of",sa.DateTime(timezone=True),nullable=False),sa.Column("review_status",sa.String(32),nullable=False),
      sa.Column("payload",postgresql.JSONB,nullable=False),sa.Column("schema_version",sa.Integer,nullable=False),
      sa.UniqueConstraint("patient_id","state_version",name="uq_clinical_state_patient_version"),sa.CheckConstraint("state_version > 0","ck_clinical_state_version_positive"))
    op.create_index("ix_clinical_state_patient_asof","patient_clinical_state_versions",["patient_id","as_of"])
    op.create_table("clinical_state_audit_events",
      sa.Column("sequence_id",sa.BigInteger,sa.Identity(),primary_key=True),sa.Column("event_id",sa.String(67),nullable=False,unique=True),
      sa.Column("patient_id",sa.String(67),nullable=False),sa.Column("state_id",sa.String(67),nullable=False),
      sa.Column("event_type",sa.String(32),nullable=False),sa.Column("occurred_at",sa.DateTime(timezone=True),nullable=False),
      sa.Column("actor_id",sa.String(128),nullable=False),sa.Column("source_event_id",sa.String(128),nullable=False),
      sa.Column("provenance",sa.String(512),nullable=False),sa.Column("detail_code",sa.String(64),nullable=False))
    for table in ("patient_clinical_state_versions","clinical_state_audit_events"):
        op.execute(f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION reject_immutable_history_mutation()")
def downgrade():raise RuntimeError("clinical state history cannot be destructively downgraded")
