"""Append-only internal API operational audit.

Revision ID: 020_api_operational_audit
Revises: 019_llm_gateway
"""
from alembic import op
import sqlalchemy as sa

revision = "020_api_operational_audit"
down_revision = "019_llm_gateway"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "api_access_audit_events",
        sa.Column("sequence_id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("event_id", sa.String(68), nullable=False, unique=True),
        sa.Column("caller_id", sa.String(128), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("purpose", sa.String(64), nullable=False),
        sa.Column("correlation_id", sa.String(128), nullable=False, index=True),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column("route_template", sa.String(256), nullable=False),
        sa.Column("method", sa.String(16), nullable=False),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("status_code", sa.Integer, nullable=False),
        sa.Column("duration_ms", sa.Float, nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status_code >= 100 AND status_code <= 599", name="ck_api_audit_status"),
        sa.CheckConstraint("duration_ms >= 0", name="ck_api_audit_duration"),
    )
    op.execute("CREATE TRIGGER api_access_audit_events_append_only BEFORE UPDATE OR DELETE ON "
               "api_access_audit_events FOR EACH ROW EXECUTE FUNCTION reject_immutable_history_mutation()")


def downgrade():
    raise RuntimeError("API operational audit history cannot be destructively downgraded")
