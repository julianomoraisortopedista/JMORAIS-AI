from pathlib import Path


ROOT = Path(__file__).parents[1]


def source(path): return (ROOT / path).read_text()


def test_api_routes_do_not_validate_jwt_and_authorization_policy_is_outside_routes():
    app = source("jmoraIs/api/app.py")
    assert "jwt.decode" not in app and "get_unverified_header" not in app
    assert "CanonicalApiAuthorizationPolicy" not in app
    assert "operations.authorization.authorize" in app


def test_identity_domain_and_ports_are_provider_agnostic():
    combined = source("jmoraIs/identity/domain.py") + source("jmoraIs/identity/ports.py")
    assert "import jwt" not in combined and "import requests" not in combined
    assert "OpenAI" not in combined and "Azure" not in combined


def test_provider_specific_code_stays_in_infrastructure_and_homologation_is_external_only():
    oidc = source("jmoraIs/infrastructure/oidc_identity.py")
    composition = source("jmoraIs/api/homologation.py")
    assert "import jwt" in oidc and "OIDCIdentityProviderAdapter" in oidc
    assert "OIDCIdentityProviderAdapter" in composition
    assert "DeterministicDevelopmentAuthenticator" not in composition
    assert "authentication=" not in composition


def test_iam_boundary_has_no_patient_or_evidence_models_and_persistence_has_no_raw_token():
    identity = "\n".join(path.read_text() for path in (ROOT / "jmoraIs/identity").glob("*.py"))
    persistence = source("jmoraIs/infrastructure/identity_persistence.py") + source("alembic/versions/021_iam_identity_governance.py")
    assert "PatientContext" not in identity and "EvidencePackage" not in identity
    for forbidden in ("access_token", "refresh_token", "password", "private_key", "clinical_payload"):
        assert forbidden not in persistence


def test_reviewer_integration_imports_canonical_reviewer_repository_contract_only():
    reviewer = source("jmoraIs/identity/reviewer.py")
    assert "ReviewerIdentity(" not in reviewer
    assert "self._reviewers.resolve" in reviewer and "self._reviewers.may_review" in reviewer
