"""IAM identity links and append-only security events.

Revision ID: 021_iam_identity_governance
Revises: 020_api_operational_audit
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "021_iam_identity_governance"
down_revision = "020_api_operational_audit"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("external_identity_links",
        sa.Column("sequence_id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("principal_id", sa.String(128), nullable=False, unique=True),
        sa.Column("provider", sa.String(128), nullable=False),
        sa.Column("external_subject", sa.String(256), nullable=False),
        sa.Column("organization_id", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("principal_type", sa.String(32), nullable=False),
        sa.Column("allowed_purposes", postgresql.JSONB, nullable=False),
        sa.Column("scoped_permissions", postgresql.JSONB, nullable=False),
        sa.Column("reviewer_id", sa.String(64), sa.ForeignKey("reviewer_identities.reviewer_id", ondelete="RESTRICT")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.UniqueConstraint("provider", "external_subject", name="uq_external_identity_provider_subject"))
    op.create_table("identity_security_events",
        sa.Column("sequence_id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("event_id", sa.String(68), nullable=False, unique=True),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("principal_id", sa.String(128)),
        sa.Column("provider", sa.String(128), nullable=False),
        sa.Column("correlation_id", sa.String(128), nullable=False, index=True),
        sa.Column("reason_code", sa.String(64), nullable=False),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False))
    op.execute("CREATE TRIGGER identity_security_events_append_only BEFORE UPDATE OR DELETE ON "
               "identity_security_events FOR EACH ROW EXECUTE FUNCTION reject_immutable_history_mutation()")


def downgrade():
    raise RuntimeError("identity governance history cannot be destructively downgraded")
