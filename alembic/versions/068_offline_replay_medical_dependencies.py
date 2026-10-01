"""Read-only visibility of exact Medical Document replay dependencies."""
from alembic import op

revision = '068_offline_medical_dependencies'
down_revision = '067_evidence_lifecycle_authority'
branch_labels = None
depends_on = None


def upgrade():
    for table in ('guideline_recommendation_set_references', 'orthopedic_assessment_set_references'):
        op.execute(f'GRANT SELECT ON {table} TO jmorais_offline_replay_verifier')
        op.execute(f'REVOKE INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER ON {table} FROM jmorais_offline_replay_verifier')


def downgrade():
    raise RuntimeError('required offline replay visibility cannot be removed')
