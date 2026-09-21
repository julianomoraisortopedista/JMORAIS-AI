"""Clinical data privacy audit boundary.

Revision ID: 010_clinical_privacy
Revises: 009_patient_context
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision="010_clinical_privacy";down_revision="009_patient_context";branch_labels=None;depends_on=None

def upgrade():
    op.create_table("clinical_data_access_audit",
      sa.Column("sequence_id",sa.BigInteger,sa.Identity(),primary_key=True),
      sa.Column("event_id",sa.String(64),nullable=False,unique=True),sa.Column("event_type",sa.String(40),nullable=False),
      sa.Column("actor_id",sa.String(128),nullable=False),sa.Column("organization_id",sa.String(128),nullable=False),
      sa.Column("pseudonymous_patient_id",sa.String(67)),sa.Column("purpose",sa.String(40),nullable=False),
      sa.Column("occurred_at",sa.DateTime(timezone=True),nullable=False),sa.Column("policy_version",sa.String(64),nullable=False),
      sa.Column("outcome",sa.String(32),nullable=False),sa.Column("reason_code",sa.String(64),nullable=False),
      sa.Column("metadata_keys",postgresql.JSONB,nullable=False))
    op.create_index("ix_clinical_audit_patient_sequence","clinical_data_access_audit",["pseudonymous_patient_id","sequence_id"])
    op.execute("""CREATE TRIGGER clinical_data_access_audit_append_only BEFORE UPDATE OR DELETE ON clinical_data_access_audit
      FOR EACH ROW EXECUTE FUNCTION reject_immutable_history_mutation()""")

def downgrade(): raise RuntimeError("clinical privacy audit history cannot be destructively downgraded")
