"""Cryptographic stream completeness checkpoints.

Revision ID: 007_crypto_checkpoints
Revises: 006_tamper_concurrency
"""
from alembic import op
import sqlalchemy as sa

revision = "007_crypto_checkpoints"
down_revision = "006_tamper_concurrency"
branch_labels = None
depends_on = None

STREAMS = (
    ("canonical_ledger_events", "claim_id", "stream_position", "event_hash", "occurred_at"),
    ("governed_clinical_audit_events", "case_id", "stream_position", "event_hash", "occurred_at"),
    ("clinical_conflict_adjudication_events", "conflict_id", "stream_position", "event_hash", "occurred_at"),
    ("governed_evidence_lifecycle_events", "governed_evidence_id", "stream_position", "event_hash", "occurred_at"),
    ("governed_evidence_versions", "evidence_package_id", "stream_version", "integrity_hash", "issued_at"),
)


def upgrade():
    op.create_table(
        "cryptographic_stream_checkpoints",
        sa.Column("checkpoint_id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("stream_namespace", sa.String(96), nullable=False),
        sa.Column("stream_id", sa.String(128), nullable=False),
        sa.Column("stream_position", sa.BigInteger(), nullable=False),
        sa.Column("head_hash", sa.String(64), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("stream_namespace", "stream_id", "stream_position",
                            name="uq_crypto_checkpoint_stream_position"),
        sa.CheckConstraint("stream_position > 0", name="ck_crypto_checkpoint_position_positive"),
    )
    op.create_index("ix_crypto_checkpoint_stream", "cryptographic_stream_checkpoints",
                    ["stream_namespace", "stream_id", "stream_position"])
    for table, owner, position, event_hash, occurred_at in STREAMS:
        op.execute(f"""
            INSERT INTO cryptographic_stream_checkpoints
                (stream_namespace, stream_id, stream_position, head_hash, recorded_at)
            SELECT '{table}', {owner}, {position}, {event_hash}, {occurred_at} FROM {table}
            ON CONFLICT DO NOTHING
        """)
    op.execute("""
        CREATE OR REPLACE FUNCTION record_cryptographic_stream_checkpoint()
        RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = public, pg_temp AS $$
        BEGIN
            INSERT INTO cryptographic_stream_checkpoints
                (stream_namespace, stream_id, stream_position, head_hash, recorded_at)
            VALUES (TG_TABLE_NAME, to_jsonb(NEW) ->> TG_ARGV[0],
                    (to_jsonb(NEW) ->> TG_ARGV[1])::bigint,
                    to_jsonb(NEW) ->> TG_ARGV[2],
                    (to_jsonb(NEW) ->> TG_ARGV[3])::timestamptz);
            RETURN NEW;
        END;
        $$
    """)
    for table, owner, position, event_hash, occurred_at in STREAMS:
        op.execute(f"""
            CREATE TRIGGER {table}_crypto_checkpoint AFTER INSERT ON {table}
            FOR EACH ROW EXECUTE FUNCTION record_cryptographic_stream_checkpoint(
                '{owner}', '{position}', '{event_hash}', '{occurred_at}')
        """)
    op.execute("""
        CREATE TRIGGER cryptographic_stream_checkpoints_append_only
        BEFORE UPDATE OR DELETE ON cryptographic_stream_checkpoints
        FOR EACH ROW EXECUTE FUNCTION reject_immutable_history_mutation()
    """)


def downgrade():
    raise RuntimeError("cryptographic completeness checkpoints cannot be destructively downgraded")
