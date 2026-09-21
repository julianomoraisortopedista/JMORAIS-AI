from pathlib import Path

import pytest

from jmoraIs.infrastructure.offline_replay import OfflineReplayVerifier, OfflineReplayVerificationError
from jmoraIs.secrets.domain import SecretPurpose, SecretReference

ROOT = Path(__file__).resolve().parents[1]


def test_verifier_requires_dedicated_secret_purpose():
    reference = SecretReference("vault", "db", SecretPurpose.POSTGRESQL_CREDENTIALS, "1")
    with pytest.raises(OfflineReplayVerificationError, match="purpose"):
        OfflineReplayVerifier(object(), reference, object())


def test_api_and_bounded_contexts_cannot_import_offline_verifier():
    prohibited = tuple((ROOT / "jmoraIs" / name) for name in (
        "api/app.py", "api/homologation.py", "clinical", "appraisal", "patient_context",
        "clinical_state", "reasoning_input", "terminology", "guideline_engine",
        "orthopedic_intelligence", "medical_documents", "audit_defense", "llm_gateway",
    ))
    for target in prohibited:
        files = (target,) if target.is_file() else tuple(target.rglob("*.py"))
        assert all("offline_replay" not in path.read_text() for path in files), target
    production = (ROOT / "jmoraIs/api/production.py").read_text()
    assert "OfflineReplayVerifier" in production
    assert "app.state" not in production.split("OfflineReplayVerifier", 1)[1].split("del verifier", 1)[0]


def test_no_http_route_exposes_replay():
    source = (ROOT / "jmoraIs/api/app.py").read_text().casefold()
    assert "offline replay" not in source and "/replay" not in source
