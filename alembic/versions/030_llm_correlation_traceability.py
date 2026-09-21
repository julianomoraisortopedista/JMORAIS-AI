"""Correlation traceability for tenant-scoped LLM operational history."""
from alembic import op
import sqlalchemy as sa

revision="030_llm_correlation";down_revision="029_terminology_governance";branch_labels=None;depends_on=None

def upgrade():
    for table in ("llm_invocations","llm_prompt_audit"):
        op.add_column(table,sa.Column("correlation_id",sa.String(128),nullable=True))
        op.create_index(f"ix_{table}_correlation_id",table,["correlation_id"])
        op.create_check_constraint(f"ck_{table}_correlation_nonempty",table,"correlation_id IS NULL OR length(trim(correlation_id)) > 0")

def downgrade():
    raise RuntimeError("LLM correlation traceability cannot be destructively downgraded")
