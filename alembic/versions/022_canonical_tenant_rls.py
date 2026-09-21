"""Canonical tenant isolation and PostgreSQL row-level security.

Revision ID: 022_canonical_tenant_rls
Revises: 021_iam_identity_governance
"""
from alembic import op
import sqlalchemy as sa


revision = "022_canonical_tenant_rls"
down_revision = "021_iam_identity_governance"
branch_labels = None
depends_on = None


TENANT_TABLES = (
    "patient_context_versions", "clinical_data_access_audit",
    "patient_clinical_state_versions", "clinical_state_audit_events",
    "clinical_reasoning_input_versions", "clinical_reasoning_input_audit",
    "governed_evidence_versions", "governed_evidence_lifecycle_events",
    "governed_clinical_audit_events", "clinical_conflict_adjudication_events",
    "guideline_recommendation_versions", "guideline_recommendation_audit",
    "orthopedic_assessment_versions", "orthopedic_assessment_audit",
    "medical_document_versions", "medical_document_audit",
    "audit_defense_versions", "audit_defense_events",
    "reviewer_identities", "external_identity_links", "api_access_audit_events",
    "llm_prompt_audit", "llm_invocations",
)


def upgrade():
    op.execute("""DO $$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='jmorais_application_writer') THEN
            CREATE ROLE jmorais_application_writer NOLOGIN NOBYPASSRLS;
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='jmorais_application_reader') THEN
            CREATE ROLE jmorais_application_reader NOLOGIN NOBYPASSRLS;
        END IF;
        EXECUTE format('GRANT jmorais_application_writer,jmorais_application_reader TO %I', current_user);
    END $$""")
    op.create_table("tenants",
        sa.Column("tenant_id", sa.String(128), primary_key=True),
        sa.Column("organization_id", sa.String(128), nullable=False, unique=True),
        sa.Column("display_name", sa.String(256), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("length(trim(tenant_id)) > 0", name="ck_tenant_id_nonempty"),
        sa.CheckConstraint("status IN ('ACTIVE','SUSPENDED','DISABLED')", name="ck_tenant_status"))
    op.execute("""INSERT INTO tenants
        (tenant_id,organization_id,display_name,status,policy_version,created_at)
        VALUES ('legacy-internal','legacy-internal','Legacy internal migration tenant','ACTIVE',
                'iam-policy-v1',CURRENT_TIMESTAMP)""")
    op.create_table("tenant_security_events",
        sa.Column("sequence_id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("event_id", sa.String(72), nullable=False, unique=True),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("tenant_id", sa.String(128)),
        sa.Column("organization_id", sa.String(128)),
        sa.Column("principal_id", sa.String(128)),
        sa.Column("correlation_id", sa.String(128), nullable=False, index=True),
        sa.Column("reason_code", sa.String(64), nullable=False),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False))
    op.execute("CREATE TRIGGER tenant_security_events_append_only BEFORE UPDATE OR DELETE ON "
               "tenant_security_events FOR EACH ROW EXECUTE FUNCTION reject_immutable_history_mutation()")

    for table in TENANT_TABLES:
        if table != "reviewer_identities":
            op.add_column(table, sa.Column("tenant_id", sa.String(128), nullable=False,
                                           server_default="legacy-internal"))
            op.alter_column(table, "tenant_id",
                server_default=sa.text("COALESCE(NULLIF(current_setting('jmorais.tenant_id', true), ''), 'legacy-internal')"))
        op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])
        op.create_check_constraint(f"ck_{table}_tenant_nonempty", table, "length(trim(tenant_id)) > 0")
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY {table}_tenant_isolation ON {table} "
            "USING (tenant_id = NULLIF(current_setting('jmorais.tenant_id', true), '')) "
            "WITH CHECK (tenant_id = NULLIF(current_setting('jmorais.tenant_id', true), ''))")

    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='jmorais_application_writer') THEN
            ALTER ROLE jmorais_application_writer NOBYPASSRLS;
            GRANT SELECT ON tenants TO jmorais_application_writer;
            GRANT SELECT,INSERT ON tenant_security_events TO jmorais_application_writer;
            GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO jmorais_application_writer;
        END IF;
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='jmorais_application_reader') THEN
            ALTER ROLE jmorais_application_reader NOBYPASSRLS;
            GRANT SELECT ON tenants,tenant_security_events TO jmorais_application_reader;
        END IF;
    END $$""")
    op.execute("GRANT USAGE ON SCHEMA public TO jmorais_application_writer,jmorais_application_reader")
    op.execute("GRANT SELECT,INSERT ON ALL TABLES IN SCHEMA public TO jmorais_application_writer")
    op.execute("GRANT SELECT ON ALL TABLES IN SCHEMA public TO jmorais_application_reader")
    op.execute("GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO jmorais_application_writer")
    op.execute("REVOKE UPDATE,DELETE,TRUNCATE ON ALL TABLES IN SCHEMA public FROM jmorais_application_writer")
    op.execute("GRANT UPDATE (role,status,active,organization_id,tenant_id,updated_at,authorization_policy_version) "
               "ON reviewer_identities TO jmorais_application_writer")
    op.execute("GRANT UPDATE (status,last_seen_at) ON external_identity_links TO jmorais_application_writer")


def downgrade():
    raise RuntimeError("tenant isolation and security history cannot be destructively downgraded")
