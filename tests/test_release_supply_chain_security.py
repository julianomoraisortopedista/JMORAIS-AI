from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import base64
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from jmoraIs import __version__
from jmoraIs.infrastructure.release_security import (
    ArtifactDigest, Ed25519SignatureVerifier, RELEASE_POLICY_VERSION, ReleaseIdentity,
    ReleaseManifest, ReleaseVerificationError, ReleaseVerifier, SignatureReference,
    load_manifest, sha256_file,
)


REVISION = "a" * 40
ALEMBIC = "060_ortho_reasoning_lineage"


def manifest(tmp_path: Path) -> tuple[ReleaseManifest, Ed25519PrivateKey]:
    artifacts = {}
    for name in ("dependency_lock", "container", "sbom", "vulnerability", "sast", "secret_scan", "provenance"):
        path = tmp_path / (name + ".json")
        path.write_text(json.dumps({"name": name}), encoding="utf-8")
        artifacts[name] = ArtifactDigest(path.name, sha256_file(path))
    identity = ReleaseIdentity(__version__, REVISION, "build-1", "3.12.13", ALEMBIC,
        artifacts["dependency_lock"].digest, artifacts["container"].digest,
        datetime(2026, 8, 16, tzinfo=timezone.utc).isoformat(), RELEASE_POLICY_VERSION)
    unsigned = ReleaseManifest(1, identity, artifacts,
        SignatureReference("UNSIGNED", "Ed25519", "ci:test", None, "test-key"),
        "783 passed", 94.0, "READY_FOR_CONTROLLED_INTERNAL_PILOT", "VALID")
    key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    signature = base64.b64encode(key.sign(unsigned.unsigned_payload())).decode()
    return replace(unsigned, signature=SignatureReference("SIGNED", "Ed25519", "ci:test", signature, "test-key")), key


def verifier(key: Ed25519PrivateKey) -> ReleaseVerifier:
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return ReleaseVerifier(Ed25519SignatureVerifier({"test-key": public}))


def verify(value: ReleaseManifest, key: Ed25519PrivateKey, root: Path) -> None:
    verifier(key).verify(value, root, expected_source_revision=REVISION,
        expected_alembic_revision=ALEMBIC, expected_version=__version__)


def test_signed_release_manifest_is_independently_verifiable(tmp_path):
    value, key = manifest(tmp_path)
    verify(value, key, tmp_path)


@pytest.mark.parametrize("artifact", ["dependency_lock", "sbom", "container", "provenance"])
def test_artifact_tampering_fails_closed(tmp_path, artifact):
    value, key = manifest(tmp_path)
    (tmp_path / value.artifacts[artifact].path).write_text("tampered", encoding="utf-8")
    with pytest.raises(ReleaseVerificationError, match="digest mismatch"):
        verify(value, key, tmp_path)


def test_invalid_signature_fails_closed(tmp_path):
    value, key = manifest(tmp_path)
    altered = replace(value, signature=replace(value.signature, signature=base64.b64encode(b"x" * 64).decode()))
    with pytest.raises(ReleaseVerificationError, match="invalid release signature"):
        verify(altered, key, tmp_path)


@pytest.mark.parametrize(("field", "message"), [
    ("source_revision", "source revision mismatch"),
    ("alembic_revision", "Alembic revision mismatch"),
])
def test_release_identity_mismatch_fails_closed(tmp_path, field, message):
    value, key = manifest(tmp_path)
    value = replace(value, identity=replace(value.identity, **{field: "wrong"}))
    with pytest.raises(ReleaseVerificationError, match=message):
        verify(value, key, tmp_path)


def test_missing_required_report_and_critical_gate_fail_closed(tmp_path):
    value, key = manifest(tmp_path)
    artifacts = dict(value.artifacts); artifacts.pop("sast")
    with pytest.raises(ReleaseVerificationError, match="missing required"):
        verify(replace(value, artifacts=artifacts), key, tmp_path)
    with pytest.raises(ReleaseVerificationError, match="COMPLETE_CASE"):
        verify(replace(value, complete_case_result="NOT_READY"), key, tmp_path)


def test_institutional_signing_pending_is_explicit_and_not_production_valid(tmp_path):
    value, key = manifest(tmp_path)
    pending = replace(value, signature=SignatureReference(
        "INSTITUTIONAL_SIGNING_PENDING", "NONE", "UNASSIGNED", None, None))
    with pytest.raises(ReleaseVerificationError, match="institutional release signature"):
        verify(pending, key, tmp_path)
    ReleaseVerifier(allow_institutional_signing_pending=True).verify(
        pending, tmp_path, expected_source_revision=REVISION,
        expected_alembic_revision=ALEMBIC, expected_version=__version__)


def test_manifest_loader_rejects_malformed_content(tmp_path):
    path = tmp_path / "manifest.json"; path.write_text("{}", encoding="utf-8")
    with pytest.raises(ReleaseVerificationError, match="malformed"):
        load_manifest(path)


def test_version_and_container_metadata_have_one_canonical_value():
    assert __version__ == "0.2.0-beta.1"
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    runtime = Path("jmoraIs/infrastructure/production_runtime.py").read_text(encoding="utf-8")
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    assert 'version = "0.1.0"' not in pyproject
    assert '"0.2.0-beta.1"' not in runtime
    assert "org.opencontainers.image.version=$JMORAIS_VERSION" in dockerfile
    assert "--require-hashes" in dockerfile


def test_release_security_stays_out_of_domain_and_clinical_layers():
    for root in (Path("jmoraIs/appraisal"), Path("jmoraIs/clinical"), Path("jmoraIs/patient_context"),
                 Path("jmoraIs/scientific_domain.py")):
        paths = [root] if root.is_file() else root.rglob("*.py")
        for path in paths:
            assert "release_security" not in path.read_text(encoding="utf-8")
