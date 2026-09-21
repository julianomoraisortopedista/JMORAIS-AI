"""Durable authoritative reviewer identity directory.

Revision ID: 008_reviewer_identity
Revises: 007_crypto_checkpoints
"""
from alembic import op
import sqlalchemy as sa

revision = "008_reviewer_identity"
down_revision = "007_crypto_checkpoints"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "reviewer_identities",
        sa.Column("reviewer_id", sa.String(64), primary_key=True),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("organization_id", sa.String(64), nullable=False),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("authorization_policy_version", sa.String(32), nullable=False),
        sa.CheckConstraint("role IN ('REVIEWER','SENIOR_REVIEWER','ADMINISTRATOR')",
                           name="ck_reviewer_identity_role"),
        sa.CheckConstraint("status IN ('ACTIVE','INACTIVE','SUSPENDED')",
                           name="ck_reviewer_identity_status"),
        sa.CheckConstraint("updated_at >= created_at", name="ck_reviewer_identity_timestamps"),
    )
    op.create_index("ix_reviewer_identity_organization", "reviewer_identities", ["organization_id"])
    op.create_index("ix_reviewer_identity_tenant", "reviewer_identities", ["tenant_id"])
    op.add_column("governed_clinical_audit_events",
                  sa.Column("reviewer_id", sa.String(64), nullable=True))
    op.execute("""
        INSERT INTO reviewer_identities
            (reviewer_id, role, status, active, organization_id, tenant_id,
             created_at, updated_at, authorization_policy_version)
        SELECT DISTINCT payload->>'reviewer_id',
               CASE WHEN payload->>'actor_role' IN ('REVIEWER','SENIOR_REVIEWER','ADMINISTRATOR')
                    THEN payload->>'actor_role' ELSE 'REVIEWER' END,
               'INACTIVE', false, 'legacy', 'legacy', occurred_at, occurred_at,
               COALESCE(payload->>'policy_version', 'legacy')
          FROM governed_clinical_audit_events
         WHERE payload->>'reviewer_id' IS NOT NULL
        ON CONFLICT DO NOTHING
    """)
    op.execute("""
        UPDATE governed_clinical_audit_events
           SET reviewer_id = payload->>'reviewer_id'
         WHERE payload->>'reviewer_id' IS NOT NULL
    """)
    op.create_foreign_key(
        "fk_clinical_audit_reviewer", "governed_clinical_audit_events",
        "reviewer_identities", ["reviewer_id"], ["reviewer_id"], ondelete="RESTRICT",
    )


def downgrade():
    raise RuntimeError("reviewer-attributed audit history cannot be destructively downgraded")
