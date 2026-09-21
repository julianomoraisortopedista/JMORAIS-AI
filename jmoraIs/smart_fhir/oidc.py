from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

import jwt

from .domain import SmartTokenRejected, SmartTokenType, SmartValidatedToken
from .ports import SmartSigningKeyPort


@dataclass(frozen=True)
class SmartTokenValidationPolicy:
    issuer: str
    audience: str
    allowed_algorithms: tuple[str, ...] = ("RS256",)
    leeway_seconds: int = 30


class SmartJwtValidator:
    """Validates a token and returns metadata only; raw tokens are never retained."""

    def __init__(self, keys: SmartSigningKeyPort, policy: SmartTokenValidationPolicy,
                 *, clock: Callable[[], datetime] | None = None):
        self._keys = keys
        self._policy = policy
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def validate(self, token: str, token_type: SmartTokenType, *, expected_nonce: str | None = None):
        if not isinstance(token, str) or token.count(".") != 2:
            raise SmartTokenRejected("malformed JWT")
        try:
            header = jwt.get_unverified_header(token)
            algorithm = header.get("alg")
            key_id = header.get("kid")
            if algorithm == "none" or algorithm not in self._policy.allowed_algorithms or not key_id:
                raise SmartTokenRejected("JWT signing policy rejected")
            key = self._keys.resolve(key_id, algorithm)
            claims = jwt.decode(
                token, key.public_key, algorithms=list(self._policy.allowed_algorithms),
                issuer=self._policy.issuer, audience=self._policy.audience,
                leeway=self._policy.leeway_seconds,
                options={"require": ["iss", "aud", "sub", "exp", "nbf", "iat"],
                         "verify_exp": False, "verify_nbf": False, "verify_iat": False},
            )
        except SmartTokenRejected:
            raise
        except jwt.PyJWTError as exc:
            raise SmartTokenRejected("JWT validation failed") from exc

        now = self._aware(self._clock())
        issued_at = self._timestamp(claims["iat"], "iat")
        not_before = self._timestamp(claims["nbf"], "nbf")
        expires_at = self._timestamp(claims["exp"], "exp")
        if expires_at.timestamp() <= now.timestamp() - self._policy.leeway_seconds:
            raise SmartTokenRejected("JWT has expired")
        if not_before.timestamp() > now.timestamp() + self._policy.leeway_seconds:
            raise SmartTokenRejected("JWT is not active")
        if issued_at.timestamp() > now.timestamp() + self._policy.leeway_seconds:
            raise SmartTokenRejected("JWT issued-at time is invalid")
        nonce = claims.get("nonce")
        if token_type is SmartTokenType.ID:
            if not expected_nonce or not isinstance(nonce, str) or not __import__("hmac").compare_digest(nonce, expected_nonce):
                raise SmartTokenRejected("ID token nonce validation failed")
        audience = claims["aud"]
        audiences = (audience,) if isinstance(audience, str) else tuple(audience)
        subject = claims["sub"]
        if not isinstance(subject, str) or not subject.strip() or not all(isinstance(item, str) for item in audiences):
            raise SmartTokenRejected("JWT identity claims are invalid")
        token_id = claims.get("jti")
        if token_id is not None and (not isinstance(token_id, str) or not token_id.strip()):
            raise SmartTokenRejected("JWT identifier is invalid")
        return SmartValidatedToken(token_type, subject, claims["iss"], audiences, issued_at,
                                   not_before, expires_at, key_id, algorithm, token_id, nonce)

    @staticmethod
    def _timestamp(value, name):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise SmartTokenRejected(f"JWT {name} is invalid")
        return datetime.fromtimestamp(value, tz=timezone.utc)

    @staticmethod
    def _aware(value):
        if value.tzinfo is None:
            raise SmartTokenRejected("validation clock must be timezone-aware")
        return value.astimezone(timezone.utc)
