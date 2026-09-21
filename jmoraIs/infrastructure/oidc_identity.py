from __future__ import annotations

from datetime import datetime, timedelta, timezone
from time import monotonic
from uuid import uuid4

import jwt
import requests

from jmoraIs.api.security import ApiMetric, ReadinessCheck
from jmoraIs.identity.configuration import OIDCProviderConfig
from jmoraIs.identity.domain import (
    AuthenticatedPrincipal, IdentityAuthenticationRejected, IdentityLinkStatus,
    IdentitySecurityEvent, IdentitySecurityEventType,
)
from jmoraIs.identity.session_domain import (
    AuthenticatedSession, SessionIdentifier, SessionValidationRejected, SessionValidationRequest,
)


class OIDCSigningKeyProvider:
    def __init__(self, config: OIDCProviderConfig, *, http_get=requests.get, clock=None, metrics=None):
        self._config, self._http_get, self._metrics = config, http_get, metrics
        self._clock = clock or (lambda: datetime.now(timezone.utc)); self._keys = {}; self._expires = None

    def resolve(self, key_id: str, algorithm: str):
        if not key_id or algorithm not in self._config.allowed_algorithms:
            raise IdentityAuthenticationRejected("signing key or algorithm is invalid")
        if self._expires is None or self._clock() >= self._expires: self.refresh()
        key = self._keys.get(key_id)
        if key is None:
            self.refresh(); key = self._keys.get(key_id)
        if key is None: raise IdentityAuthenticationRejected("signing key cannot be established")
        if key.algorithm_name and key.algorithm_name != algorithm:
            raise IdentityAuthenticationRejected("signing-key algorithm mismatch")
        return key.key

    def refresh(self) -> None:
        started = monotonic()
        try:
            response = self._http_get(self._config.jwks_uri, timeout=5); response.raise_for_status()
            values = response.json().get("keys", ())
            parsed = {value["kid"]: jwt.PyJWK.from_dict(value) for value in values if value.get("kid")}
            if not parsed: raise IdentityAuthenticationRejected("JWKS contains no signing keys")
            self._keys = parsed; self._expires = self._clock() + timedelta(seconds=self._config.jwks_cache_seconds)
            status = 200
        except Exception as exc:
            status = 503
            raise IdentityAuthenticationRejected("identity-provider signing keys are unavailable") from exc
        finally:
            if self._metrics is not None:
                self._metrics.observe(ApiMetric("/identity/jwks-refresh", "IDENTITY", status,
                    round((monotonic() - started) * 1000, 3), self._clock(), "KEY_REFRESH"))

    def readiness(self) -> ReadinessCheck:
        try: self.refresh(); return ReadinessCheck("identity_signing_keys", True, "AVAILABLE")
        except IdentityAuthenticationRejected: return ReadinessCheck("identity_signing_keys", False, "UNAVAILABLE")


class OIDCIdentityProviderAdapter:
    homologation_safe = True

    def __init__(self, config: OIDCProviderConfig, keys, links, audit, *, clock=None, metrics=None,
                 tenant_resolution=None, tenant_binding=None, session_validation=None):
        self._config, self._keys, self._links, self._audit, self._metrics = config, keys, links, audit, metrics
        self._tenant_resolution, self._tenant_binding = tenant_resolution, tenant_binding
        self._session_validation = session_validation
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def validate(self, token: str, correlation_id: str) -> AuthenticatedPrincipal:
        started = monotonic(); event_type = IdentitySecurityEventType.AUTHENTICATION_FAILURE
        try:
            if not token or token.count(".") != 2: raise IdentityAuthenticationRejected("token is malformed")
            header = jwt.get_unverified_header(token)
            algorithm, key_id = header.get("alg"), header.get("kid")
            if not algorithm or algorithm.lower() == "none" or algorithm not in self._config.allowed_algorithms:
                raise IdentityAuthenticationRejected("token algorithm is not allowed")
            if header.get("typ") != self._config.token_type: raise IdentityAuthenticationRejected("token type is invalid")
            try: key = self._keys.resolve(key_id, algorithm)
            except IdentityAuthenticationRejected:
                event_type = IdentitySecurityEventType.SIGNING_KEY_FAILURE
                raise
            claims = jwt.decode(token, key, algorithms=list(self._config.allowed_algorithms),
                issuer=self._config.issuer, audience=self._config.audience,
                leeway=self._config.clock_skew_seconds,
                options={"require": list(set(self._config.required_claims) | {"sub", "iat", "exp", "auth_time"})})
            try:
                authentication_time = datetime.fromtimestamp(claims["auth_time"], timezone.utc)
            except (TypeError, ValueError, OverflowError) as exc:
                raise IdentityAuthenticationRejected("authentication time is invalid") from exc
            if authentication_time > self._clock() + timedelta(seconds=self._config.clock_skew_seconds):
                raise IdentityAuthenticationRejected("authentication time is invalid")
            subject = claims.get("sub")
            if not isinstance(subject, str) or not subject.strip(): raise IdentityAuthenticationRejected("subject is required")
            raw_roles = claims.get(self._config.role_claim, ())
            if isinstance(raw_roles, str): raw_roles = (raw_roles,)
            if not isinstance(raw_roles, (list, tuple)) or any(not isinstance(role, str) for role in raw_roles):
                event_type = IdentitySecurityEventType.UNKNOWN_ROLE
                raise IdentityAuthenticationRejected("identity role claim is invalid")
            mapping = dict(self._config.role_mapping)
            unknown = tuple(role for role in raw_roles if role not in mapping)
            if unknown:
                event_type = IdentitySecurityEventType.UNKNOWN_ROLE
                raise IdentityAuthenticationRejected("identity contains an untrusted role")
            roles = tuple(sorted({mapping[role] for role in raw_roles if role in mapping}))
            if not roles: raise IdentityAuthenticationRejected("identity has no authorized role")
            organization = claims.get(self._config.organization_claim)
            if not isinstance(organization, str) or not organization: raise IdentityAuthenticationRejected("organization is required")
            if self._tenant_resolution is not None and self._tenant_binding is not None:
                tenant = self._tenant_resolution.resolve(organization, principal_id=None,
                    correlation_id=correlation_id, policy_version=self._config.policy_version)
                from jmoraIs.tenancy.domain import TenantContext
                preliminary = TenantContext(tenant.tenant_id, organization, "pre-authenticated-subject",
                    "IDENTITY_RESOLUTION", "AUTHENTICATION", self._config.policy_version, correlation_id)
                with self._tenant_binding.bind_tenant(preliminary):
                    link = self._links.get(self._config.provider_id, subject)
            else:
                tenant = None
                link = self._links.get(self._config.provider_id, subject)
            if link is None or link.status is not IdentityLinkStatus.ACTIVE:
                event_type = IdentitySecurityEventType.IDENTITY_LINK_FAILURE
                raise IdentityAuthenticationRejected("identity link is unavailable")
            if link.organization_id != organization:
                event_type = IdentitySecurityEventType.IDENTITY_LINK_FAILURE
                raise IdentityAuthenticationRejected("organization link mismatch")
            if tenant is not None and link.tenant_id != tenant.tenant_id:
                event_type = IdentitySecurityEventType.IDENTITY_LINK_FAILURE
                raise IdentityAuthenticationRejected("tenant link mismatch")
            issued, expires = datetime.fromtimestamp(claims["iat"], timezone.utc), datetime.fromtimestamp(claims["exp"], timezone.utc)
            principal = AuthenticatedPrincipal(link.principal_id, subject, self._config.provider_id,
                organization, link.tenant_id, roles, authentication_time, "OIDC",
                claims.get("sid") or claims.get("jti"), self._config.policy_version, issued, expires,
                link.principal_type, link.allowed_purposes, link.scoped_permissions)
            if self._session_validation is not None:
                session_id = claims.get("sid") or claims.get("jti")
                if not isinstance(session_id, str) or not session_id:
                    raise IdentityAuthenticationRejected("governed session identifier is required")
                request = SessionValidationRequest(AuthenticatedSession(SessionIdentifier(session_id),
                    link.principal_id, link.tenant_id, organization, self._config.issuer, link.principal_type,
                    issued, expires, self._config.policy_version, self._clock()), claims.get("jti"),
                    str(claims.get("token_class", "ACCESS")), correlation_id)
                try:
                    if self._tenant_binding is not None:
                        from jmoraIs.tenancy.domain import TenantContext
                        context = TenantContext(link.tenant_id, organization, link.principal_id,
                            roles[0], "AUTHENTICATION", self._config.policy_version, correlation_id)
                        with self._tenant_binding.bind_tenant(context): self._session_validation.validate(request)
                    else: self._session_validation.validate(request)
                except SessionValidationRejected as exc:
                    raise IdentityAuthenticationRejected("session validation rejected") from exc
            event_type = IdentitySecurityEventType.AUTHENTICATION_SUCCESS
            self._event(event_type, principal.principal_id, correlation_id, "AUTHENTICATED")
            return principal
        except jwt.ExpiredSignatureError as exc:
            event_type = IdentitySecurityEventType.EXPIRED_TOKEN
            self._event(event_type, None, correlation_id, "EXPIRED_TOKEN")
            raise IdentityAuthenticationRejected("token is expired") from exc
        except (jwt.InvalidIssuerError, jwt.InvalidAudienceError) as exc:
            event_type = IdentitySecurityEventType.INVALID_ISSUER_AUDIENCE
            self._event(event_type, None, correlation_id, "INVALID_ISSUER_OR_AUDIENCE")
            raise IdentityAuthenticationRejected("issuer or audience is invalid") from exc
        except jwt.PyJWTError as exc:
            self._event(event_type, None, correlation_id, "TOKEN_VALIDATION_FAILED")
            raise IdentityAuthenticationRejected("token validation failed") from exc
        except IdentityAuthenticationRejected:
            self._event(event_type, None, correlation_id, "AUTHENTICATION_REJECTED")
            raise
        finally:
            if self._metrics is not None:
                self._metrics.observe(ApiMetric("/identity/token-validation", "IDENTITY",
                    200 if event_type is IdentitySecurityEventType.AUTHENTICATION_SUCCESS else 401,
                    round((monotonic() - started) * 1000, 3), self._clock(), event_type.value))

    def readiness(self) -> ReadinessCheck:
        keys = self._keys.readiness(); links = self._links.readiness()
        ready = keys.ready and links.ready
        return ReadinessCheck("identity_provider", ready, "AVAILABLE" if ready else "UNAVAILABLE")

    def _event(self, kind, principal_id, correlation_id, reason):
        self._audit.append(IdentitySecurityEvent("iam_" + uuid4().hex, kind, principal_id,
            self._config.provider_id, correlation_id, reason, self._config.policy_version, self._clock()))
