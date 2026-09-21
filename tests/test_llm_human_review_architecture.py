from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_llm_review_boundary_has_no_provider_or_evaluation_dependency():
    application = (ROOT / "jmoraIs/llm_human_review/application.py").read_text()
    package = "\n".join(path.read_text() for path in (ROOT / "jmoraIs/llm_human_review").glob("*.py"))
    assert "LLMResponse" not in application
    assert "ProviderAdapter" not in package and "MockProvider" not in package
    assert "evaluation" not in package
    assert "class ReviewerRole" not in (ROOT / "jmoraIs/llm_human_review/domain.py").read_text()


def test_review_is_draft_only_lifecycle_queried_and_never_actionable():
    source = (ROOT / "jmoraIs/llm_human_review/application.py").read_text()
    assert "GovernedLLMDraft" in source and "current_status" in source
    assert "externally_actionable" not in source or "False" in source
    assert "PubMed" not in source and "Crossref" not in source and "diagnos" not in source.casefold()


def test_persistence_has_rls_append_only_and_no_update_delete_api():
    migration = (ROOT / "alembic/versions/038_llm_human_review.py").read_text()
    ports = (ROOT / "jmoraIs/llm_human_review/ports.py").read_text()
    assert "ENABLE ROW LEVEL SECURITY" in migration and "append_only" in migration
    assert "def update" not in ports and "def delete" not in ports

def test_primary_postgresql_proof_composes_oidc_session_tenancy_secrets_and_persisted_reviewer():
    source=(ROOT/"tests/test_llm_human_review_postgresql.py").read_text()
    for required in ("OIDCIdentityProviderAdapter","CanonicalSessionSecurityService","TrustedTenantResolutionService","CanonicalTenantAuthorizationService","ManagedAttestationFactory","PostgreSQLReviewerIdentityRepository"):
        assert required in source
    assert "AuthenticatedPrincipal(" not in source and "ReviewerIdentity(" not in source
    assert "GovernedDraftAttestor(DRAFT_KEY)" not in source
    application=(ROOT/"jmoraIs/llm_human_review/application.py").read_text();domain=(ROOT/"jmoraIs/llm_human_review/domain.py").read_text()
    assert "LLMHumanReviewSecurityEvent" in application
    audit_fields=domain.split("class LLMHumanReviewSecurityEvent:",1)[1]
    assert "reviewable_content" not in audit_fields
