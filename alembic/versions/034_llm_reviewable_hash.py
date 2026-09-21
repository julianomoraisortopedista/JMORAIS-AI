"""Persist independent reviewable content hash on LLM invocations."""
from alembic import op
import sqlalchemy as sa
revision="034_llm_reviewable_hash";down_revision="033_gateway_input";branch_labels=None;depends_on=None
def upgrade():
    op.add_column("llm_invocations",sa.Column("reviewable_content_hash",sa.String(64),nullable=True))
    op.create_check_constraint("ck_llm_reviewable_content_hash","llm_invocations","reviewable_content_hash IS NULL OR length(reviewable_content_hash) = 64")
def downgrade():
    raise RuntimeError("LLM invocation reviewable hash history cannot be destructively downgraded")
