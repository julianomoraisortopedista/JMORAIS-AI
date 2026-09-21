"""Owner-issued exact persisted DefensePackage references."""
from alembic import op
import sqlalchemy as sa

revision="045_defense_exact_ref"
down_revision="044_pgi_checkpoints"
branch_labels=None
depends_on=None


def upgrade():
    op.create_table("audit_defense_persisted_references",
        sa.Column("sequence_id",sa.BigInteger,sa.Identity(),primary_key=True),
        sa.Column("reference_id",sa.String(68),nullable=False,unique=True),
        sa.Column("tenant_id",sa.String(128),nullable=False),
        sa.Column("stream_id",sa.String(68),nullable=False),
        sa.Column("package_version",sa.Integer,nullable=False),
        sa.Column("package_id",sa.String(68),sa.ForeignKey("audit_defense_versions.package_id",ondelete="RESTRICT"),nullable=False),
        sa.Column("policy_version",sa.String(256),nullable=False),
        sa.Column("integrity_hash",sa.String(64),nullable=False),
        sa.Column("issued_at",sa.DateTime(timezone=True),nullable=False),
        sa.UniqueConstraint("tenant_id","stream_id","package_version","package_id",name="uq_audit_defense_exact_reference"),
        sa.CheckConstraint("package_version > 0",name="ck_audit_defense_reference_version"),
        sa.CheckConstraint("length(integrity_hash)=64",name="ck_audit_defense_reference_integrity"))
    op.create_index("ix_audit_defense_reference_exact","audit_defense_persisted_references",
        ["tenant_id","reference_id","stream_id","package_version"])
    op.execute("CREATE TRIGGER audit_defense_persisted_references_append_only BEFORE UPDATE OR DELETE ON audit_defense_persisted_references FOR EACH ROW EXECUTE FUNCTION reject_immutable_history_mutation()")
    op.execute("ALTER TABLE audit_defense_persisted_references ENABLE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY audit_defense_persisted_references_tenant_isolation ON audit_defense_persisted_references USING (tenant_id = NULLIF(current_setting('jmorais.tenant_id', true), '')) WITH CHECK (tenant_id = NULLIF(current_setting('jmorais.tenant_id', true), ''))")
    op.execute("GRANT SELECT,INSERT ON audit_defense_persisted_references TO jmorais_application_writer")
    op.execute("GRANT SELECT ON audit_defense_persisted_references TO jmorais_application_reader")
    op.execute("GRANT USAGE,SELECT ON SEQUENCE audit_defense_persisted_references_sequence_id_seq TO jmorais_application_writer")
    op.execute("REVOKE UPDATE,DELETE,TRUNCATE ON audit_defense_persisted_references FROM jmorais_application_writer,jmorais_application_reader")


def downgrade():
    raise RuntimeError("exact DefensePackage reference history cannot be destructively downgraded")
