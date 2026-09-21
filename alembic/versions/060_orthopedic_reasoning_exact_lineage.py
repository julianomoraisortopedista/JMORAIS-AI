"""Exact Clinical Reasoning lineage for Orthopedic Assessment sets."""
from alembic import op
import sqlalchemy as sa
revision="060_ortho_reasoning_lineage";down_revision="059_reasoning_input_exact_ref";branch_labels=None;depends_on=None
def upgrade():
    op.add_column("orthopedic_assessment_versions",sa.Column("reasoning_input_reference_id",sa.String(68)))
    op.add_column("orthopedic_assessment_versions",sa.Column("reasoning_lineage_status",sa.String(72),nullable=False,server_default="LEGACY_MISSING_CLINICAL_REASONING_INPUT_REFERENCE"))
    op.create_index("ix_orthopedic_reasoning_exact_lineage","orthopedic_assessment_versions",["tenant_id","reasoning_input_reference_id"])
    op.create_check_constraint("ck_orthopedic_reasoning_lineage_status","orthopedic_assessment_versions","reasoning_lineage_status IN ('EXACT','LEGACY_MISSING_CLINICAL_REASONING_INPUT_REFERENCE')")
def downgrade():raise RuntimeError("orthopedic exact reasoning lineage cannot be destructively downgraded")
