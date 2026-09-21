"""Restart-equivalent LLM invocation operational metadata."""
from alembic import op
import sqlalchemy as sa

revision="031_llm_invocation_metadata";down_revision="030_llm_correlation";branch_labels=None;depends_on=None

def upgrade():
    op.add_column("llm_invocations",sa.Column("output_classification",sa.String(32),nullable=True))
    op.add_column("llm_invocations",sa.Column("temperature",sa.Float,nullable=True))
    op.add_column("llm_invocations",sa.Column("seed",sa.BigInteger,nullable=True))
    op.create_check_constraint("ck_llm_invocations_output_classification","llm_invocations","output_classification IS NULL OR output_classification IN ('DRAFT','REVIEW_REQUIRED','BLOCKED','APPROVED_FOR_REVIEW')")
    op.create_check_constraint("ck_llm_invocations_temperature","llm_invocations","temperature IS NULL OR (temperature >= 0 AND temperature <= 2)")

def downgrade():
    raise RuntimeError("LLM invocation metadata cannot be destructively downgraded")
