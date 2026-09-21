"""persist trusted LLM upstream artifact reference"""
from alembic import op
import sqlalchemy as sa

revision="033_gateway_input"
down_revision="032_llm_invocation_context"
branch_labels=None
depends_on=None

def upgrade():
    op.add_column("llm_invocations",sa.Column("upstream_artifact_type",sa.String(64),nullable=True))
    op.add_column("llm_invocations",sa.Column("upstream_artifact_id",sa.String(160),nullable=True))
    op.add_column("llm_invocations",sa.Column("upstream_artifact_version",sa.Integer(),nullable=True))
    op.create_check_constraint("ck_llm_upstream_reference_complete","llm_invocations","(upstream_artifact_type IS NULL AND upstream_artifact_id IS NULL AND upstream_artifact_version IS NULL) OR (upstream_artifact_type IS NOT NULL AND upstream_artifact_id IS NOT NULL AND upstream_artifact_version > 0)")

def downgrade():
    op.drop_constraint("ck_llm_upstream_reference_complete","llm_invocations",type_="check")
    op.drop_column("llm_invocations","upstream_artifact_version")
    op.drop_column("llm_invocations","upstream_artifact_id")
    op.drop_column("llm_invocations","upstream_artifact_type")
