from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Mapping
from uuid import uuid4

from .domain import (
    SmartAuthenticationAuditEvent, SmartAuthenticationResult, SmartFhirError,
    SmartLaunchContextRejected, SmartTokenType,
)
from .launch_context import SmartLaunchContextParser
from .oauth import SmartPkceS256
from .ports import SmartAuthenticationAuditPort
from .scopes import SmartScopeParser


@dataclass(frozen=True)
class SmartAuthenticationCommand:
    access_token: str
    id_token: str | None
    scopes: str
    launch_context: Mapping[str, str]
    pkce_verifier: str
    pkce_challenge: str
    pkce_method: str
    expected_nonce: str | None
    correlation_id: str


class SmartFhirAuthenticationService:
    """Protocol validation only. Clinical authorization remains outside this boundary."""

    def __init__(self, access_validator, id_validator, audit: SmartAuthenticationAuditPort,
                 *, issuer: str, policy_version: str,
                 clock: Callable[[], datetime] | None = None):
        self._access = access_validator
        self._id = id_validator
        self._audit = audit
        self._issuer = issuer
        self._policy_version = policy_version
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._pkce = SmartPkceS256()
        self._scopes = SmartScopeParser()
        self._launch = SmartLaunchContextParser()

    def authenticate(self, command: SmartAuthenticationCommand):
        subject = None
        try:
            if not isinstance(command, SmartAuthenticationCommand) or not command.correlation_id.strip():
                raise SmartLaunchContextRejected("typed command and correlation ID are required")
            self._pkce.verify(command.pkce_verifier, command.pkce_challenge, command.pkce_method)
            access = self._access.validate(command.access_token, SmartTokenType.ACCESS)
            subject = access.subject
            identity = None
            if command.id_token is not None:
                identity = self._id.validate(command.id_token, SmartTokenType.ID,
                                             expected_nonce=command.expected_nonce)
                if identity.subject != access.subject:
                    raise SmartLaunchContextRejected("access and ID token subjects differ")
            scopes = self._scopes.parse(command.scopes)
            launch = self._launch.parse(dict(command.launch_context))
            if any(scope.raw == "launch/patient" for scope in scopes) and launch.patient_reference is None:
                raise SmartLaunchContextRejected("launch/patient requires patient launch metadata")
            result = SmartAuthenticationResult(access, identity, scopes, launch,
                                               command.correlation_id, self._policy_version)
            self._record("SUCCESS", "SMART_AUTHENTICATED", command.correlation_id, subject)
            return result
        except SmartFhirError as exc:
            correlation = command.correlation_id if isinstance(command, SmartAuthenticationCommand) else "rejected"
            self._record("FAILURE", exc.__class__.__name__, correlation, subject)
            raise

    def _record(self, outcome, reason, correlation_id, subject):
        self._audit.append(SmartAuthenticationAuditEvent(
            str(uuid4()), outcome, reason, correlation_id, self._issuer, subject,
            self._policy_version, self._clock(),
        ))
