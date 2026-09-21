from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from jmoraIs.api.identity_security import CanonicalApiAuthorizationPolicy, ExternalIdentityApiAuthenticator
from jmoraIs.api.security import CallerCredentials, CallerRole, PurposeOfUse
from jmoraIs.clinical.review_governance import (
    InMemoryReviewerAuthorizationAdapter, ReviewerIdentity, ReviewerRole, ReviewerStatus,
)
from jmoraIs.identity.configuration import OIDCProviderConfig
from jmoraIs.identity.domain import (
    ExternalIdentityLink, IdentityAuthenticationRejected, IdentityAuthorizationRejected,
    IdentityLinkStatus, IdentitySecurityEventType, PrincipalType,
)
from jmoraIs.identity.reviewer import AuthenticatedReviewerResolver
from jmoraIs.infrastructure.oidc_identity import OIDCIdentityProviderAdapter, OIDCSigningKeyProvider


NOW = datetime.now(timezone.utc).replace(microsecond=0)


def oidc_config() -> OIDCProviderConfig:
    return OIDCProviderConfig(
        "local-oidc", "https://issuer.example", "jmorais-internal-api",
        "https://issuer.example/.well-known/openid-configuration", "https://issuer.example/jwks",
        ("RS256",), 10, ("sub", "iat", "exp", "auth_time", "roles", "organization_id"),
        "roles", "organization_id",
        (("svc", "INTERNAL_SERVICE"), ("reviewer", "CLINICAL_REVIEWER"), ("admin", "ADMINISTRATOR")),
    )


def link(*, status=IdentityLinkStatus.ACTIVE, principal_type=PrincipalType.SERVICE,
         reviewer_id=None, subject="external-subject") -> ExternalIdentityLink:
    return ExternalIdentityLink(
        "principal-1", "local-oidc", subject, "organization-1", "tenant-1", status, principal_type,
        ("INTERNAL_OPERATIONS", "CLINICAL_REVIEW", "ADMINISTRATION"), ("api:read",), reviewer_id,
        NOW - timedelta(days=1), NOW, "iam-policy-v1")


class MemoryLinks:
    def __init__(self, value): self.value = value
    def get(self, provider, subject):
        return self.value if self.value and (provider, subject) == (self.value.provider, self.value.external_subject) else None
    def readiness(self):
        from jmoraIs.api.security import ReadinessCheck
        return ReadinessCheck("identity_repository", True, "AVAILABLE")


class MemoryAudit:
    def __init__(self): self.events = []
    def append(self, event): self.events.append(event)


class StaticKeys:
    def __init__(self, key, available=True): self.key, self.available = key, available
    def resolve(self, key_id, algorithm):
        if not self.available: raise IdentityAuthenticationRejected("signing key cannot be established")
        return self.key
    def readiness(self):
        from jmoraIs.api.security import ReadinessCheck
        return ReadinessCheck("identity_signing_keys", self.available, "AVAILABLE" if self.available else "UNAVAILABLE")


@pytest.fixture
def keys():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private, private.public_key()


def token(private, **changes):
    claims = {"iss": "https://issuer.example", "aud": "jmorais-internal-api", "sub": "external-subject",
        "iat": int((NOW - timedelta(seconds=1)).timestamp()), "exp": int((NOW + timedelta(minutes=5)).timestamp()),
        "auth_time": int((NOW - timedelta(minutes=1)).timestamp()), "roles": ["svc"],
        "organization_id": "organization-1", "jti": "session-1"}
    claims.update(changes)
    return jwt.encode(claims, private, algorithm="RS256", headers={"kid": "key-1", "typ": "JWT"})


def provider(public, *, identity_link=None, available=True):
    audit = MemoryAudit()
    adapter = OIDCIdentityProviderAdapter(oidc_config(), StaticKeys(public, available),
        MemoryLinks(identity_link or link()), audit)
    return adapter, audit


def test_valid_principal_role_mapping_service_identity_and_purpose(keys):
    private, public = keys; adapter, audit = provider(public)
    principal = adapter.validate(token(private), "corr-1")
    assert principal.roles == ("INTERNAL_SERVICE",) and principal.session_id == "session-1"
    assert principal.principal_type is PrincipalType.SERVICE and principal.scoped_permissions == ("api:read",)
    caller = ExternalIdentityApiAuthenticator(adapter).authenticate(
        CallerCredentials(token(private), "INTERNAL_OPERATIONS"), "corr-2")
    assert caller.role is CallerRole.INTERNAL_SERVICE and caller.organization_id == "organization-1"
    assert audit.events[-1].event_type is IdentitySecurityEventType.AUTHENTICATION_SUCCESS


@pytest.mark.parametrize(("changes", "message", "kind"), [
    ({"exp": int((NOW - timedelta(minutes=1)).timestamp())}, "expired", IdentitySecurityEventType.EXPIRED_TOKEN),
    ({"iss": "https://wrong.example"}, "issuer or audience", IdentitySecurityEventType.INVALID_ISSUER_AUDIENCE),
    ({"aud": "wrong-api"}, "issuer or audience", IdentitySecurityEventType.INVALID_ISSUER_AUDIENCE),
    ({"roles": ["caller-supplied-admin"]}, "untrusted role", IdentitySecurityEventType.UNKNOWN_ROLE),
])
def test_expired_issuer_audience_and_unknown_roles_fail_closed(keys, changes, message, kind):
    private, public = keys; adapter, audit = provider(public)
    with pytest.raises(IdentityAuthenticationRejected, match=message): adapter.validate(token(private, **changes), "corr")
    assert audit.events[-1].event_type is kind


def test_malformed_unsigned_invalid_signature_missing_subject_and_invalid_role_shape(keys):
    private, public = keys; adapter, audit = provider(public)
    bad_private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    values = ["not-a-token", token(bad_private), token(private, sub=""), token(private, roles=42)]
    for index, value in enumerate(values):
        with pytest.raises(IdentityAuthenticationRejected): adapter.validate(value, f"corr-{index}")
    unsigned = jwt.encode({"sub": "x"}, key="", algorithm="none", headers={"typ": "JWT"})
    with pytest.raises(IdentityAuthenticationRejected): adapter.validate(unsigned, "corr-none")
    assert all("not-a-token" not in repr(event) for event in audit.events)


@pytest.mark.parametrize("status", [IdentityLinkStatus.SUSPENDED, IdentityLinkStatus.DISABLED])
def test_suspended_and_disabled_links_are_rejected(keys, status):
    private, public = keys; adapter, audit = provider(public, identity_link=link(status=status))
    with pytest.raises(IdentityAuthenticationRejected, match="link"): adapter.validate(token(private), "corr")
    assert audit.events[-1].event_type is IdentitySecurityEventType.IDENTITY_LINK_FAILURE


def test_purpose_and_authorization_are_separate_and_service_never_inherits_reviewer(keys):
    private, public = keys
    restricted = replace(link(), allowed_purposes=("INTERNAL_OPERATIONS",))
    adapter, audit = provider(public, identity_link=restricted)
    with pytest.raises(IdentityAuthenticationRejected, match="purpose"):
        ExternalIdentityApiAuthenticator(adapter).authenticate(CallerCredentials(token(private), "CLINICAL_REVIEW"), "corr")
    policy = CanonicalApiAuthorizationPolicy(audit, clock=lambda: NOW)
    caller = ExternalIdentityApiAuthenticator(adapter).authenticate(
        CallerCredentials(token(private), "INTERNAL_OPERATIONS"), "corr-auth")
    with pytest.raises(IdentityAuthorizationRejected): policy.authorize(caller, "ORTHOPEDIC")
    assert audit.events[-1].event_type is IdentitySecurityEventType.AUTHORIZATION_DENIAL


def test_reviewer_link_reuses_canonical_reviewer_governance(keys):
    private, public = keys
    reviewer_link = link(principal_type=PrincipalType.HUMAN, reviewer_id="reviewer-1")
    adapter, _ = provider(public, identity_link=reviewer_link)
    principal = adapter.validate(token(private, roles=["reviewer"]), "corr")
    canonical = ReviewerIdentity("reviewer-1", ReviewerRole.REVIEWER,
                                 organization_id="organization-1", tenant_id="tenant-1")
    resolver = AuthenticatedReviewerResolver(MemoryLinks(reviewer_link), InMemoryReviewerAuthorizationAdapter((canonical,)))
    assert resolver.resolve(principal) == canonical
    suspended = replace(canonical, status=ReviewerStatus.SUSPENDED)
    with pytest.raises(IdentityAuthorizationRejected):
        AuthenticatedReviewerResolver(MemoryLinks(reviewer_link), InMemoryReviewerAuthorizationAdapter((suspended,))).resolve(principal)
    with pytest.raises(IdentityAuthorizationRejected): resolver.resolve(replace(principal, principal_type=PrincipalType.SERVICE))


def test_jwks_key_rotation_refresh_and_provider_unavailability(keys):
    old_private, _ = keys
    new_private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    def jwk(private, kid):
        value = jwt.algorithms.RSAAlgorithm.to_jwk(private.public_key(), as_dict=True)
        return {**value, "kid": kid, "alg": "RS256", "use": "sig"}
    responses = [{"keys": [jwk(old_private, "old")]}, {"keys": [jwk(new_private, "new")]}]
    class Response:
        def __init__(self, payload): self.payload = payload
        def raise_for_status(self): pass
        def json(self): return self.payload
    calls = []
    def get(url, timeout): calls.append(url); return Response(responses.pop(0))
    signing = OIDCSigningKeyProvider(oidc_config(), http_get=get)
    assert signing.resolve("old", "RS256")
    assert signing.resolve("new", "RS256")
    assert len(calls) == 2
    unavailable = OIDCSigningKeyProvider(oidc_config(), http_get=lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError()))
    assert not unavailable.readiness().ready


def test_provider_readiness_fails_when_keys_are_unavailable(keys):
    _, public = keys; adapter, _ = provider(public, available=False)
    assert not adapter.readiness().ready


def test_symmetric_or_unsigned_oidc_algorithms_are_configuration_errors():
    base = oidc_config()
    with pytest.raises(ValueError, match="unsafe"):
        replace(base, allowed_algorithms=("HS256",))
    with pytest.raises(ValueError, match="unsafe"):
        replace(base, allowed_algorithms=("none",))
