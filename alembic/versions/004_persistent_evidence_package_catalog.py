"""Persistent append-only Evidence Package catalog.

Revision ID: 004_package_catalog
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "004_package_catalog"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    for name, key in (("canonical_ledger_claims", "claim_id"), ("canonical_ledger_fragments", "fragment_id")):
        op.create_table(name, sa.Column(key, sa.String(64), primary_key=True), sa.Column("payload", postgresql.JSONB(), nullable=False))
    op.create_table("canonical_ledger_supports", sa.Column("support_id", sa.String(64), primary_key=True), sa.Column("claim_id", sa.String(64), nullable=False), sa.Column("payload", postgresql.JSONB(), nullable=False))
    op.create_index("ix_canonical_support_claim", "canonical_ledger_supports", ["claim_id"])
    op.create_table("canonical_ledger_events", sa.Column("sequence_id", sa.BigInteger(), primary_key=True, autoincrement=True), sa.Column("event_id", sa.String(64), nullable=False, unique=True), sa.Column("claim_id", sa.String(64), nullable=False), sa.Column("event_hash", sa.String(64), nullable=False, unique=True), sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False), sa.Column("payload", postgresql.JSONB(), nullable=False))
    op.create_index("ix_canonical_event_claim", "canonical_ledger_events", ["claim_id"])
    op.create_table(
        "evidence_package_catalog",
        sa.Column("package_id", sa.String(64), primary_key=True),
        sa.Column("package_payload", postgresql.JSONB(), nullable=False),
        sa.Column("association_payload", postgresql.JSONB(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "evidence_package_versions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("package_id", sa.String(64), sa.ForeignKey("evidence_package_catalog.package_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("package_version", sa.String(64), nullable=False),
        sa.Column("integrity_hash", sa.String(64), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_evidence_package_versions_package", "evidence_package_versions", ["package_id"])
    op.execute("""
    CREATE OR REPLACE FUNCTION reject_package_catalog_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN RAISE EXCEPTION 'Evidence Package catalog is append-only: % prohibited on %', TG_OP, TG_TABLE_NAME; END; $$
    """)
    for table in ("canonical_ledger_claims", "canonical_ledger_fragments", "canonical_ledger_supports", "canonical_ledger_events", "evidence_package_catalog", "evidence_package_versions"):
        op.execute(f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION reject_package_catalog_mutation()")


def downgrade():
    for table in ("evidence_package_versions", "evidence_package_catalog", "canonical_ledger_events", "canonical_ledger_supports", "canonical_ledger_fragments", "canonical_ledger_claims"):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only ON {table}")
    op.drop_table("evidence_package_versions")
    op.drop_table("evidence_package_catalog")
    op.drop_table("canonical_ledger_events")
    op.drop_table("canonical_ledger_supports")
    op.drop_table("canonical_ledger_fragments")
    op.drop_table("canonical_ledger_claims")
    op.execute("DROP FUNCTION IF EXISTS reject_package_catalog_mutation()")
