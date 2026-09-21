"""Append-only production deployment audit metadata."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "025_production_composition"
down_revision = "024_session_revocation_replay"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("deployment_audit_events",
        sa.Column("sequence_id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("event_id", sa.String(72), nullable=False, unique=True),
        sa.Column("release_id", sa.String(128), nullable=False), sa.Column("build_id", sa.String(128), nullable=False),
        sa.Column("source_revision", sa.String(128), nullable=False), sa.Column("application_version", sa.String(64), nullable=False),
        sa.Column("migration_revision", sa.String(128), nullable=False), sa.Column("python_version", sa.String(64), nullable=False),
        sa.Column("policy_versions", postgresql.JSONB, nullable=False), sa.Column("provider_references", postgresql.JSONB, nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False))
    op.execute("CREATE TRIGGER deployment_audit_events_append_only BEFORE UPDATE OR DELETE ON deployment_audit_events FOR EACH ROW EXECUTE FUNCTION reject_immutable_history_mutation()")
    op.execute("GRANT SELECT,INSERT ON deployment_audit_events TO jmorais_application_writer")
    op.execute("GRANT SELECT ON deployment_audit_events TO jmorais_application_reader")
    op.execute("GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO jmorais_application_writer")

def downgrade(): raise RuntimeError("deployment audit cannot be destructively downgraded")
