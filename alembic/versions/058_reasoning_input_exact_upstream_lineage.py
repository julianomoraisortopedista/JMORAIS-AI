"""Clinical Reasoning Input exact upstream lineage metadata."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision="058_reasoning_exact_lineage";down_revision="057_human_review_exact_ref";branch_labels=None;depends_on=None
def upgrade():
    op.add_column("clinical_reasoning_input_versions",sa.Column("clinical_state_reference_id",sa.String(68)))
    op.add_column("clinical_reasoning_input_versions",sa.Column("governed_evidence_reference_ids",postgresql.JSONB,nullable=False,server_default=sa.text("'[]'::jsonb")))
    op.add_column("clinical_reasoning_input_versions",sa.Column("exact_upstream_lineage_status",sa.String(96),nullable=False,server_default="LEGACY_MISSING_PERSISTED_CLINICAL_REASONING_INPUT_REFERENCE"))
    op.create_check_constraint("ck_reasoning_exact_evidence_refs_array","clinical_reasoning_input_versions","jsonb_typeof(governed_evidence_reference_ids)='array'")
    op.create_check_constraint("ck_reasoning_exact_lineage_status","clinical_reasoning_input_versions","exact_upstream_lineage_status IN ('EXACT','LEGACY_MISSING_PERSISTED_CLINICAL_REASONING_INPUT_REFERENCE')")
    op.create_index("ix_reasoning_exact_state_reference","clinical_reasoning_input_versions",["tenant_id","clinical_state_reference_id"])
def downgrade():raise RuntimeError("exact Clinical Reasoning upstream lineage cannot be destructively downgraded")
