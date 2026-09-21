from pathlib import Path


ROOT = Path(__file__).parents[1]


def source(path): return (ROOT / path).read_text()


def test_tenancy_domain_and_ports_have_no_postgresql_or_api_dependency():
    combined = source("jmoraIs/tenancy/domain.py") + source("jmoraIs/tenancy/ports.py")
    assert "sqlalchemy" not in combined.lower() and "psycopg" not in combined.lower()
    assert "jmoraIs.api" not in combined


def test_homologation_uses_runtime_role_tenant_binding_and_rls_readiness():
    composition = source("jmoraIs/api/homologation.py")
    assert "SecretBackedDatabaseEngine" in composition
    assert "TenantContextBinder" in composition
    assert "PostgreSQLRLSReadiness" in composition
    assert "create_engine(" not in composition


def test_public_api_repositories_do_not_add_optional_caller_tenant_filters():
    app = source("jmoraIs/api/app.py")
    assert "x-tenant-id" in app and "TENANT_SPOOFING_REJECTED" in app
    for path in ("jmoraIs/reasoning_input/persistence.py", "jmoraIs/appraisal/persistence.py",
                 "jmoraIs/guideline_engine/persistence.py", "jmoraIs/orthopedic_intelligence/persistence.py",
                 "jmoraIs/medical_documents/persistence.py", "jmoraIs/audit_defense/persistence.py"):
        assert "caller_tenant" not in source(path)


def test_migration_enables_database_rls_for_every_required_public_resource_family():
    migration = source("alembic/versions/022_canonical_tenant_rls.py")
    for table in ("clinical_reasoning_input_versions", "governed_evidence_versions",
                  "guideline_recommendation_versions", "orthopedic_assessment_versions",
                  "medical_document_versions", "audit_defense_versions", "reviewer_identities",
                  "external_identity_links", "api_access_audit_events"):
        assert f'"{table}"' in migration
    assert "ENABLE ROW LEVEL SECURITY" in migration and "NOBYPASSRLS" in migration
