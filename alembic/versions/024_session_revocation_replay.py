"""Session revocation and JTI replay metadata."""
from alembic import op
import sqlalchemy as sa

revision = "024_session_revocation_replay"
down_revision = "023_managed_secrets_keys"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("authenticated_sessions",
        sa.Column("sequence_id", sa.BigInteger, sa.Identity(), primary_key=True), sa.Column("session_id", sa.String(256), nullable=False, unique=True),
        sa.Column("principal_id", sa.String(128), nullable=False, index=True), sa.Column("tenant_id", sa.String(64), nullable=False, index=True),
        sa.Column("organization_id", sa.String(128), nullable=False), sa.Column("issuer", sa.String(256), nullable=False),
        sa.Column("principal_type", sa.String(32), nullable=False), sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False, index=True), sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column("recognized_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("token_replay_records",
        sa.Column("sequence_id", sa.BigInteger, sa.Identity(), primary_key=True), sa.Column("jti_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("session_id", sa.String(256), nullable=False), sa.Column("principal_id", sa.String(128), nullable=False),
        sa.Column("tenant_id", sa.String(64), nullable=False), sa.Column("issuer", sa.String(256), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False, index=True), sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("single_use", sa.Boolean, nullable=False), sa.Column("policy_version", sa.String(64), nullable=False))
    op.create_table("session_security_events",
        sa.Column("sequence_id", sa.BigInteger, sa.Identity(), primary_key=True), sa.Column("event_id", sa.String(68), nullable=False, unique=True),
        sa.Column("event_type", sa.String(64), nullable=False), sa.Column("session_id", sa.String(256)),
        sa.Column("principal_id", sa.String(128), nullable=False, index=True), sa.Column("tenant_id", sa.String(64), nullable=False, index=True),
        sa.Column("reason_code", sa.String(64), nullable=False), sa.Column("correlation_id", sa.String(128), nullable=False, index=True),
        sa.Column("policy_version", sa.String(64), nullable=False), sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False))
    for table in ("authenticated_sessions", "token_replay_records", "session_security_events"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY {table}_tenant_isolation ON {table} USING (tenant_id = current_setting('jmorais.tenant_id', true)) WITH CHECK (tenant_id = current_setting('jmorais.tenant_id', true))")
        op.execute(f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION reject_immutable_history_mutation()")
    op.execute("GRANT SELECT,INSERT ON authenticated_sessions,token_replay_records,session_security_events TO jmorais_application_writer")
    op.execute("GRANT SELECT ON authenticated_sessions,token_replay_records,session_security_events TO jmorais_application_reader")
    op.execute("GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO jmorais_application_writer")

def downgrade(): raise RuntimeError("session security history cannot be destructively downgraded")
