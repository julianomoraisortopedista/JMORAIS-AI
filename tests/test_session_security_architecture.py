from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def test_routes_do_not_implement_session_or_replay_logic():
    source = (ROOT / "jmoraIs/api/app.py").read_text()
    assert "jti_hash" not in source and "SessionStatus" not in source

def test_domain_and_application_are_provider_independent_and_raw_tokens_are_not_persisted():
    domain = (ROOT / "jmoraIs/identity/session_domain.py").read_text()
    application = (ROOT / "jmoraIs/identity/session_application.py").read_text()
    persistence = (ROOT / "jmoraIs/infrastructure/session_persistence.py").read_text()
    assert "sqlalchemy" not in domain.lower() and "sqlalchemy" not in application.lower()
    assert "jwt" not in domain.lower() and "import jwt" not in application.lower()
    assert "raw_token" not in persistence and "bearer_token" not in persistence

def test_session_validation_precedes_api_caller_context_and_human_service_policies_are_separate():
    provider = (ROOT / "jmoraIs/infrastructure/oidc_identity.py").read_text()
    assert provider.index("self._session_validation.validate") < provider.index("AUTHENTICATION_SUCCESS")
    application = (ROOT / "jmoraIs/identity/session_application.py").read_text()
    assert "PrincipalType.HUMAN" in application and "PrincipalType.SERVICE" not in application
