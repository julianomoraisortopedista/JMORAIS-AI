"""Persist metadata-only Gateway input trust artifacts and invocation linkage."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision="043_persisted_gateway_inputs"
down_revision="042_stage11_stage12_traceability"
branch_labels=None
depends_on=None

def upgrade():
    op.create_table("persisted_gateway_inputs",
        sa.Column("sequence_id",sa.BigInteger,sa.Identity(),primary_key=True),
        sa.Column("persisted_gateway_input_id",sa.String(68),nullable=False,unique=True),
        sa.Column("tenant_id",sa.String(128),nullable=False),sa.Column("artifact_type",sa.String(64),nullable=False),
        sa.Column("artifact_id",sa.String(128),nullable=False),sa.Column("artifact_version",sa.Integer,nullable=False),
        sa.Column("source_context",sa.String(64),nullable=False),sa.Column("integrity_reference",sa.String(128),nullable=False),
        sa.Column("policy_version",sa.String(256),nullable=False),sa.Column("dto_hash",sa.String(64),nullable=False),
        sa.Column("issued_at",sa.DateTime(timezone=True),nullable=False),sa.Column("attestation",sa.String(64),nullable=False),
        sa.Column("key_provider",sa.String(64),nullable=False),sa.Column("key_id",sa.String(128),nullable=False),
        sa.Column("key_version",sa.String(64),nullable=False),sa.Column("record_integrity_hash",sa.String(64),nullable=False),
        sa.Column("payload",postgresql.JSONB,nullable=False),sa.Column("schema_version",sa.Integer,nullable=False),
        sa.CheckConstraint("artifact_version > 0",name="ck_persisted_gateway_input_version"),
        sa.CheckConstraint("length(dto_hash)=64 AND length(attestation)=64 AND length(record_integrity_hash)=64",name="ck_persisted_gateway_input_hashes"))
    op.create_index("ix_persisted_gateway_input_upstream","persisted_gateway_inputs",["tenant_id","artifact_type","artifact_id","artifact_version"])
    op.execute("CREATE TRIGGER persisted_gateway_inputs_append_only BEFORE UPDATE OR DELETE ON persisted_gateway_inputs FOR EACH ROW EXECUTE FUNCTION reject_immutable_history_mutation()")
    op.execute("ALTER TABLE persisted_gateway_inputs ENABLE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY persisted_gateway_inputs_tenant_isolation ON persisted_gateway_inputs USING (tenant_id = NULLIF(current_setting('jmorais.tenant_id', true), '')) WITH CHECK (tenant_id = NULLIF(current_setting('jmorais.tenant_id', true), ''))")
    op.execute("GRANT SELECT,INSERT ON persisted_gateway_inputs TO jmorais_application_writer")
    op.execute("GRANT SELECT ON persisted_gateway_inputs TO jmorais_application_reader")
    op.execute("GRANT USAGE,SELECT ON SEQUENCE persisted_gateway_inputs_sequence_id_seq TO jmorais_application_writer")
    op.execute("REVOKE UPDATE,DELETE,TRUNCATE ON persisted_gateway_inputs FROM jmorais_application_writer,jmorais_application_reader")
    op.add_column("llm_invocations",sa.Column("persisted_gateway_input_id",sa.String(68)))
    op.create_foreign_key("fk_llm_invocation_persisted_gateway_input","llm_invocations","persisted_gateway_inputs",["persisted_gateway_input_id"],["persisted_gateway_input_id"],ondelete="RESTRICT")
    op.create_index("ix_llm_invocation_persisted_gateway_input","llm_invocations",["tenant_id","persisted_gateway_input_id"])

def downgrade():raise RuntimeError("persisted Gateway input trust history cannot be destructively downgraded")
