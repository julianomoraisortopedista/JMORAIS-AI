"""Grant the offline verifier its exact Audit Defense replay dependency."""
from alembic import op


revision = "064_replay_defense_select"
down_revision = "063_defense_native_sha256"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "GRANT SELECT ON audit_defense_versions "
        "TO jmorais_offline_replay_verifier"
    )
    op.execute(
        "REVOKE INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER "
        "ON audit_defense_versions FROM jmorais_offline_replay_verifier"
    )


def downgrade():
    op.execute(
        "REVOKE SELECT ON audit_defense_versions "
        "FROM jmorais_offline_replay_verifier"
    )
