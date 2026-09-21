from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class SecretBoundaryError(RuntimeError): pass
class SecretResolutionRejected(SecretBoundaryError): pass
class SecretPurposeRejected(SecretBoundaryError): pass
class KeyOperationRejected(SecretBoundaryError): pass


class SecretPurpose(str, Enum):
    POSTGRESQL_CREDENTIALS = "POSTGRESQL_CREDENTIALS"
    OFFLINE_REPLAY_DATABASE_CREDENTIAL = "OFFLINE_REPLAY_DATABASE_CREDENTIAL"
    OIDC_PROVIDER_CREDENTIAL = "OIDC_PROVIDER_CREDENTIAL"
    PSEUDONYMIZATION_HMAC = "PSEUDONYMIZATION_HMAC"
    PROVIDER_API_CREDENTIAL = "PROVIDER_API_CREDENTIAL"
    SIGNING_KEY = "SIGNING_KEY"


class KeyState(str, Enum):
    ACTIVE = "ACTIVE"
    ROTATING = "ROTATING"
    RETIRED = "RETIRED"
    REVOKED = "REVOKED"


class SecretSecurityEventType(str, Enum):
    RESOLUTION_FAILURE = "SECRET_RESOLUTION_FAILURE"
    ROTATION = "KEY_ROTATION"
    REVOCATION = "KEY_REVOCATION"
    RETIRED_KEY_USE = "RETIRED_KEY_USE"
    UNAUTHORIZED_PURPOSE = "UNAUTHORIZED_SECRET_PURPOSE"
    PROVIDER_UNAVAILABLE = "SECRET_PROVIDER_UNAVAILABLE"


def _required(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip(): raise SecretBoundaryError(f"{name} is required")


@dataclass(frozen=True)
class SecretReference:
    provider: str
    reference: str
    purpose: SecretPurpose
    version: str | None = None
    def __post_init__(self):
        _required(self.provider, "provider"); _required(self.reference, "reference")


@dataclass(frozen=True)
class KeyReference:
    provider: str
    key_id: str
    version: str
    purpose: SecretPurpose
    def __post_init__(self):
        _required(self.provider, "provider"); _required(self.key_id, "key_id"); _required(self.version, "version")


@dataclass(frozen=True)
class ManagedKeyMetadata:
    reference: KeyReference
    state: KeyState
    created_at: datetime
    activated_at: datetime | None
    retired_at: datetime | None
    revoked_at: datetime | None
    policy_version: str
    def __post_init__(self):
        _required(self.policy_version, "policy_version")
        if self.created_at.tzinfo is None: raise SecretBoundaryError("key timestamp must be timezone-aware")


@dataclass(frozen=True)
class PseudonymizationResult:
    pseudonymous_id: str
    key_id: str
    key_version: str
    policy_version: str


@dataclass(frozen=True)
class SecretSecurityEvent:
    event_id: str
    event_type: SecretSecurityEventType
    provider: str
    reference: str
    version: str | None
    actor_id: str
    purpose: SecretPurpose
    occurred_at: datetime
    policy_version: str
    outcome: str
