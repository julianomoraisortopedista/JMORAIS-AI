"""Add immutable Stage-11 document reference to DefensePackage history."""
from alembic import op
import sqlalchemy as sa

revision="042_stage11_stage12_traceability"
down_revision="041_authorized_ingestion_records"
branch_labels=None
depends_on=None

def upgrade():
    op.add_column("audit_defense_versions",sa.Column("stage11_document_stream_id",sa.String(68)))
    op.add_column("audit_defense_versions",sa.Column("stage11_document_id",sa.String(68)))
    op.add_column("audit_defense_versions",sa.Column("stage11_document_version",sa.Integer))
    op.add_column("audit_defense_versions",sa.Column("stage11_document_integrity_hash",sa.String(64)))
    op.create_check_constraint("ck_audit_defense_stage11_reference_complete","audit_defense_versions","(stage11_document_stream_id IS NULL AND stage11_document_id IS NULL AND stage11_document_version IS NULL AND stage11_document_integrity_hash IS NULL) OR (stage11_document_stream_id IS NOT NULL AND stage11_document_id IS NOT NULL AND stage11_document_version > 0 AND length(stage11_document_integrity_hash)=64)")
    op.create_foreign_key("fk_audit_defense_stage11_document_version","audit_defense_versions","medical_document_versions",["stage11_document_stream_id","stage11_document_version"],["document_stream_id","version"],ondelete="RESTRICT")
    op.create_index("ix_audit_defense_stage11_document","audit_defense_versions",["tenant_id","stage11_document_stream_id","stage11_document_version"])

def downgrade():
    raise RuntimeError("Stage-11/12 traceability history cannot be destructively downgraded")
