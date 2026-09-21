"""Append-only tenant-scoped COMPLETE_CASE acceptance manifests."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision="049_e2e_manifest"
down_revision="048_orthopedic_exact_ref"
branch_labels=None
depends_on=None

def upgrade():
    op.create_table("e2e_acceptance_manifests",
        sa.Column("sequence_id",sa.BigInteger,sa.Identity(),primary_key=True),
        sa.Column("execution_id",sa.String(128),nullable=False,unique=True),
        sa.Column("case_id",sa.String(128),nullable=False),
        sa.Column("tenant_id",sa.String(128),nullable=False),
        sa.Column("correlation_id",sa.String(128),nullable=False),
        sa.Column("stages",postgresql.JSONB,nullable=False),
        sa.Column("policy_versions",postgresql.JSONB,nullable=False),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False))
    op.create_index("ix_e2e_acceptance_manifest_tenant","e2e_acceptance_manifests",["tenant_id","execution_id"])
    op.execute("CREATE TRIGGER e2e_acceptance_manifests_append_only BEFORE UPDATE OR DELETE ON e2e_acceptance_manifests FOR EACH ROW EXECUTE FUNCTION reject_immutable_history_mutation()")
    op.execute("ALTER TABLE e2e_acceptance_manifests ENABLE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY e2e_acceptance_manifests_tenant_isolation ON e2e_acceptance_manifests USING (tenant_id = NULLIF(current_setting('jmorais.tenant_id', true), '')) WITH CHECK (tenant_id = NULLIF(current_setting('jmorais.tenant_id', true), ''))")
    op.execute("GRANT SELECT,INSERT ON e2e_acceptance_manifests TO jmorais_application_writer")
    op.execute("GRANT SELECT ON e2e_acceptance_manifests TO jmorais_application_reader")
    op.execute("GRANT USAGE,SELECT ON SEQUENCE e2e_acceptance_manifests_sequence_id_seq TO jmorais_application_writer")
    op.execute("REVOKE UPDATE,DELETE,TRUNCATE ON e2e_acceptance_manifests FROM jmorais_application_writer,jmorais_application_reader")

def downgrade():
    raise RuntimeError("acceptance evidence cannot be destructively downgraded")
