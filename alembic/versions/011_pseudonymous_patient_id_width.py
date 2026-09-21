"""Canonical pseudonymous patient identifier width.

Revision ID: 011_patient_id_width
Revises: 010_clinical_privacy
"""
from alembic import op
import sqlalchemy as sa

revision="011_patient_id_width";down_revision="010_clinical_privacy";branch_labels=None;depends_on=None

def upgrade():
    op.alter_column("patient_context_versions","patient_id",existing_type=sa.String(64),type_=sa.String(67),existing_nullable=False)

def downgrade():
    raise RuntimeError("canonical pseudonymous identifiers cannot be safely truncated")
