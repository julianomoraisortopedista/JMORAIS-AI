"""Governed clinical persistence.

Revision ID: 005_governed_clinical
Revises: 004_package_catalog
"""
from alembic import op
import sqlalchemy as sa

revision = "005_governed_clinical"
down_revision = "004_package_catalog"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("governed_evidence_versions",
        sa.Column("sequence_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("governed_evidence_id", sa.String(64), nullable=False, unique=True),
        sa.Column("evidence_package_id", sa.String(64), nullable=False, index=True),
        sa.Column("stream_version", sa.Integer(), nullable=False),
        sa.Column("integrity_hash", sa.String(64), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint("evidence_package_id", "stream_version", name="uq_governed_evidence_stream_version"))
    for table, owner in (
        ("governed_clinical_audit_events", "case_id"),
        ("clinical_conflict_adjudication_events", "conflict_id"),
        ("governed_evidence_lifecycle_events", "governed_evidence_id"),
    ):
        op.create_table(table,
            sa.Column("sequence_id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("event_id", sa.String(64), nullable=False, unique=True),
            sa.Column(owner, sa.String(128), nullable=False, index=True),
            sa.Column("event_hash", sa.String(64), nullable=False),
            sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False))


def downgrade():
    raise RuntimeError("append-only governed clinical history cannot be destructively downgraded")
