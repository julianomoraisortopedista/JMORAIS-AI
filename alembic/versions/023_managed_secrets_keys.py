"""Managed secret/key metadata and append-only security audit.

Revision ID: 023_managed_secrets_keys
Revises: 022_canonical_tenant_rls
"""
from alembic import op
import sqlalchemy as sa

revision="023_managed_secrets_keys"
down_revision="022_canonical_tenant_rls"
branch_labels=None
depends_on=None


def upgrade():
    op.create_table("managed_key_metadata",
        sa.Column("provider",sa.String(64),primary_key=True),sa.Column("key_id",sa.String(256),primary_key=True),
        sa.Column("key_version",sa.String(64),primary_key=True),sa.Column("purpose",sa.String(64),nullable=False),
        sa.Column("state",sa.String(32),nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),
        sa.Column("activated_at",sa.DateTime(timezone=True)),sa.Column("retired_at",sa.DateTime(timezone=True)),
        sa.Column("revoked_at",sa.DateTime(timezone=True)),sa.Column("policy_version",sa.String(64),nullable=False),
        sa.CheckConstraint("state IN ('ACTIVE','ROTATING','RETIRED','REVOKED')",name="ck_managed_key_state"))
    op.create_table("secret_security_events",
        sa.Column("sequence_id",sa.BigInteger,sa.Identity(),primary_key=True),
        sa.Column("event_id",sa.String(72),nullable=False,unique=True),sa.Column("event_type",sa.String(64),nullable=False),
        sa.Column("provider",sa.String(64),nullable=False),sa.Column("reference",sa.String(256),nullable=False),
        sa.Column("version",sa.String(64)),sa.Column("actor_id",sa.String(128),nullable=False),
        sa.Column("purpose",sa.String(64),nullable=False),sa.Column("occurred_at",sa.DateTime(timezone=True),nullable=False),
        sa.Column("policy_version",sa.String(64),nullable=False),sa.Column("outcome",sa.String(64),nullable=False))
    op.create_table("managed_key_state_events",
        sa.Column("sequence_id",sa.BigInteger,sa.Identity(),primary_key=True),
        sa.Column("event_id",sa.String(72),nullable=False,unique=True),sa.Column("provider",sa.String(64),nullable=False),
        sa.Column("key_id",sa.String(256),nullable=False),sa.Column("key_version",sa.String(64),nullable=False),
        sa.Column("state",sa.String(32),nullable=False),sa.Column("occurred_at",sa.DateTime(timezone=True),nullable=False),
        sa.Column("policy_version",sa.String(64),nullable=False))
    op.execute("CREATE TRIGGER secret_security_events_append_only BEFORE UPDATE OR DELETE ON secret_security_events "
               "FOR EACH ROW EXECUTE FUNCTION reject_immutable_history_mutation()")
    op.execute("CREATE TRIGGER managed_key_state_events_append_only BEFORE UPDATE OR DELETE ON managed_key_state_events "
               "FOR EACH ROW EXECUTE FUNCTION reject_immutable_history_mutation()")
    op.execute("GRANT SELECT,INSERT ON managed_key_metadata,managed_key_state_events,secret_security_events TO jmorais_application_writer")
    op.execute("GRANT SELECT ON managed_key_metadata,managed_key_state_events,secret_security_events TO jmorais_application_reader")
    op.execute("GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO jmorais_application_writer")


def downgrade():
    raise RuntimeError("managed key governance history cannot be destructively downgraded")
