"""Fail-closed, provider-neutral release supply-chain verification."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from hashlib import sha256
import base64
import json
from pathlib import Path
from typing import Protocol

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


RELEASE_POLICY_VERSION = "supply-chain-policy-v1"
REQUIRED_REPORTS = ("sbom", "vulnerability", "sast", "secret_scan", "provenance")


class ReleaseVerificationError(RuntimeError):
    """Raised when any release trust-chain invariant is absent or invalid."""


def sha256_file(path: str | Path) -> str:
    digest = sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


@dataclass(frozen=True)
class ArtifactDigest:
    path: str
    digest: str

    def __post_init__(self) -> None:
        if not self.path or not self.digest.startswith("sha256:") or len(self.digest) != 71:
            raise ValueError("complete SHA-256 artifact reference is required")


@dataclass(frozen=True)
class ReleaseIdentity:
    application_version: str
    source_revision: str
    build_id: str
    python_version: str
    alembic_revision: str
    dependency_lock_digest: str
    container_digest: str
    build_timestamp: str
    policy_version: str = RELEASE_POLICY_VERSION

    def __post_init__(self) -> None:
        values = asdict(self)
        if not all(isinstance(value, str) and value for value in values.values()):
            raise ValueError("complete release identity is required")
        if not self.dependency_lock_digest.startswith("sha256:"):
            raise ValueError("dependency lock must be content addressed")
        if not self.container_digest.startswith("sha256:"):
            raise ValueError("container must be content addressed")
        datetime.fromisoformat(self.build_timestamp.replace("Z", "+00:00"))


@dataclass(frozen=True)
class SignatureReference:
    status: str
    algorithm: str
    signer_identity: str
    signature: str | None
    public_key_reference: str | None


@dataclass(frozen=True)
class ReleaseManifest:
    schema_version: int
    identity: ReleaseIdentity
    artifacts: dict[str, ArtifactDigest]
    signature: SignatureReference
    test_summary: str
    coverage_percent: float
    complete_case_result: str
    cryptographic_replay_result: str

    def unsigned_payload(self) -> bytes:
        value = asdict(self)
        value.pop("signature")
        return canonical_json(value)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class SignatureVerificationPort(Protocol):
    def verify(self, payload: bytes, signature: SignatureReference) -> None: ...


class Ed25519SignatureVerifier:
    """Verifies detached signatures; private signing material stays external."""

    def __init__(self, trusted_public_keys: dict[str, bytes]) -> None:
        self._keys = dict(trusted_public_keys)

    def verify(self, payload: bytes, signature: SignatureReference) -> None:
        if signature.algorithm != "Ed25519" or not signature.signature or not signature.public_key_reference:
            raise ReleaseVerificationError("missing production-grade detached signature")
        encoded_key = self._keys.get(signature.public_key_reference)
        if encoded_key is None:
            raise ReleaseVerificationError("untrusted signing key reference")
        try:
            Ed25519PublicKey.from_public_bytes(encoded_key).verify(
                base64.b64decode(signature.signature, validate=True), payload
            )
        except (InvalidSignature, ValueError) as exc:
            raise ReleaseVerificationError("invalid release signature") from exc


class ReleaseVerifier:
    def __init__(self, signature_verifier: SignatureVerificationPort | None = None, *,
                 allow_institutional_signing_pending: bool = False) -> None:
        self._signature_verifier = signature_verifier
        self._allow_pending = allow_institutional_signing_pending

    def verify(self, manifest: ReleaseManifest, root: str | Path, *,
               expected_source_revision: str, expected_alembic_revision: str,
               expected_version: str) -> None:
        if manifest.schema_version != 1:
            raise ReleaseVerificationError("unsupported release manifest schema")
        identity = manifest.identity
        if identity.source_revision != expected_source_revision:
            raise ReleaseVerificationError("source revision mismatch")
        if identity.alembic_revision != expected_alembic_revision:
            raise ReleaseVerificationError("Alembic revision mismatch")
        if identity.application_version != expected_version:
            raise ReleaseVerificationError("application version mismatch")
        if identity.policy_version != RELEASE_POLICY_VERSION:
            raise ReleaseVerificationError("release policy mismatch")
        missing = set(REQUIRED_REPORTS + ("dependency_lock", "container")) - set(manifest.artifacts)
        if missing:
            raise ReleaseVerificationError("missing required release artifacts: " + ", ".join(sorted(missing)))
        base = Path(root).resolve()
        for name, artifact in manifest.artifacts.items():
            target = (base / artifact.path).resolve()
            if base not in target.parents and target != base:
                raise ReleaseVerificationError(f"artifact path escapes release root: {name}")
            if not target.is_file() or sha256_file(target) != artifact.digest:
                raise ReleaseVerificationError(f"artifact digest mismatch: {name}")
        if manifest.artifacts["dependency_lock"].digest != identity.dependency_lock_digest:
            raise ReleaseVerificationError("dependency lock identity mismatch")
        if manifest.artifacts["container"].digest != identity.container_digest:
            raise ReleaseVerificationError("container identity mismatch")
        if manifest.coverage_percent < 90:
            raise ReleaseVerificationError("coverage gate failed")
        if manifest.complete_case_result != "READY_FOR_CONTROLLED_INTERNAL_PILOT":
            raise ReleaseVerificationError("COMPLETE_CASE gate failed")
        if manifest.cryptographic_replay_result != "VALID":
            raise ReleaseVerificationError("cryptographic replay gate failed")
        if manifest.signature.status == "INSTITUTIONAL_SIGNING_PENDING":
            if not self._allow_pending:
                raise ReleaseVerificationError("institutional release signature is required")
        elif self._signature_verifier is None:
            raise ReleaseVerificationError("signature verifier is not configured")
        else:
            self._signature_verifier.verify(manifest.unsigned_payload(), manifest.signature)


def load_manifest(path: str | Path) -> ReleaseManifest:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    try:
        return ReleaseManifest(
            schema_version=raw["schema_version"],
            identity=ReleaseIdentity(**raw["identity"]),
            artifacts={key: ArtifactDigest(**value) for key, value in raw["artifacts"].items()},
            signature=SignatureReference(**raw["signature"]),
            test_summary=raw["test_summary"], coverage_percent=float(raw["coverage_percent"]),
            complete_case_result=raw["complete_case_result"],
            cryptographic_replay_result=raw["cryptographic_replay_result"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ReleaseVerificationError("malformed release manifest") from exc
