"""PostgreSQL tamper resistance and concurrency invariants.

Revision ID: 006_tamper_concurrency
Revises: 005_governed_clinical
"""
from alembic import op
import sqlalchemy as sa


revision = "006_tamper_concurrency"
down_revision = "005_governed_clinical"
branch_labels = None
depends_on = None


EVENT_STREAMS = (
    ("canonical_ledger_events", "claim_id", "canonical_ledger"),
    ("governed_clinical_audit_events", "case_id", "clinical_audit"),
    ("clinical_conflict_adjudication_events", "conflict_id", "conflict"),
    ("governed_evidence_lifecycle_events", "governed_evidence_id", "lifecycle"),
)

IMMUTABLE_TABLES = (
    "canonical_ledger_claims", "canonical_ledger_fragments", "canonical_ledger_supports",
    "canonical_ledger_events", "evidence_package_catalog", "evidence_package_versions",
    "governed_evidence_versions", "governed_clinical_audit_events",
    "clinical_conflict_adjudication_events", "governed_evidence_lifecycle_events",
)


def upgrade():
    op.create_foreign_key(
        "fk_canonical_support_claim", "canonical_ledger_supports", "canonical_ledger_claims",
        ["claim_id"], ["claim_id"], ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_canonical_event_claim", "canonical_ledger_events", "canonical_ledger_claims",
        ["claim_id"], ["claim_id"], ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_governed_evidence_package", "governed_evidence_versions", "evidence_package_catalog",
        ["evidence_package_id"], ["package_id"], ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_lifecycle_governed_evidence", "governed_evidence_lifecycle_events",
        "governed_evidence_versions", ["governed_evidence_id"], ["governed_evidence_id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_governed_evidence_stream_version_positive", "governed_evidence_versions",
        "stream_version > 0",
    )
    op.create_check_constraint(
        "ck_conflict_adjudication_state", "clinical_conflict_adjudication_events",
        "payload->>'state' IN ('OPEN','UNDER_REVIEW','RESOLVED','UNRESOLVED','ESCALATED')",
    )
    op.create_check_constraint(
        "ck_governed_evidence_lifecycle_state", "governed_evidence_lifecycle_events",
        "payload->>'status' IN ('ACTIVE','REVIEW_REQUIRED','SUPERSEDED','INVALIDATED')",
    )

    for table, owner, prefix in EVENT_STREAMS:
        op.add_column(table, sa.Column("stream_position", sa.BigInteger(), nullable=True))
        op.add_column(table, sa.Column("previous_event_hash", sa.String(64), nullable=True))
        op.execute(f"""
            WITH ordered AS (
                SELECT sequence_id,
                       row_number() OVER (PARTITION BY {owner} ORDER BY sequence_id) AS position,
                       lag(event_hash) OVER (PARTITION BY {owner} ORDER BY sequence_id) AS previous_hash
                FROM {table}
            )
            UPDATE {table} target
               SET stream_position = ordered.position,
                   previous_event_hash = ordered.previous_hash
              FROM ordered
             WHERE target.sequence_id = ordered.sequence_id
        """)
        op.alter_column(table, "stream_position", nullable=False)
        op.create_unique_constraint(
            f"uq_{prefix}_stream_position", table, [owner, "stream_position"],
        )
        op.create_check_constraint(
            f"ck_{prefix}_position_positive", table, "stream_position > 0",
        )

    op.execute("""
        CREATE OR REPLACE FUNCTION reject_immutable_history_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION USING
                ERRCODE = '55000',
                MESSAGE = format('append-only violation: %s prohibited on %s', TG_OP, TG_TABLE_NAME);
        END;
        $$
    """)
    for table in IMMUTABLE_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only ON {table}")
        op.execute(f"""
            CREATE TRIGGER {table}_append_only
            BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION reject_immutable_history_mutation()
        """)

    op.execute("""
        CREATE OR REPLACE FUNCTION enforce_event_stream_chain()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            owner_value text;
            latest_position bigint;
            latest_hash text;
        BEGIN
            owner_value := to_jsonb(NEW) ->> TG_ARGV[0];
            PERFORM pg_advisory_xact_lock(hashtextextended(TG_TABLE_NAME || ':' || owner_value, 0));
            EXECUTE format(
                'SELECT stream_position, event_hash FROM %I WHERE %I = $1 ORDER BY stream_position DESC LIMIT 1',
                TG_TABLE_NAME, TG_ARGV[0]
            ) INTO latest_position, latest_hash USING owner_value;
            IF NEW.stream_position <> COALESCE(latest_position, 0) + 1 THEN
                RAISE EXCEPTION USING ERRCODE = '40001', MESSAGE = 'non-contiguous event stream position';
            END IF;
            IF NEW.previous_event_hash IS DISTINCT FROM latest_hash THEN
                RAISE EXCEPTION USING ERRCODE = '23000', MESSAGE = 'invalid previous event hash linkage';
            END IF;
            RETURN NEW;
        END;
        $$
    """)
    for table, owner, _prefix in EVENT_STREAMS:
        op.execute(f"""
            CREATE TRIGGER {table}_stream_chain
            BEFORE INSERT ON {table}
            FOR EACH ROW EXECUTE FUNCTION enforce_event_stream_chain('{owner}')
        """)


def downgrade():
    raise RuntimeError(
        "ST-20 protects immutable clinical/scientific history; destructive downgrade requires an explicit archival migration"
    )
