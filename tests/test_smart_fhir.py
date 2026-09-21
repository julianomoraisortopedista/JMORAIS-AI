from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from jmoraIs.smart_fhir.application import SmartAuthenticationCommand, SmartFhirAuthenticationService
from jmoraIs.smart_fhir.domain import (
    SmartConfigurationRejected, SmartLaunchContextRejected, SmartPkceRejected,
    SmartScopeRejected, SmartTokenRejected, SmartTokenType,
)
from jmoraIs.smart_fhir.infrastructure import InMemorySmartAuthenticationAudit
from jmoraIs.smart_fhir.jwks import StaticSmartJwks
from jmoraIs.smart_fhir.launch_context import SmartLaunchContextParser
from jmoraIs.smart_fhir.oauth import SmartPkceS256
from jmoraIs.smart_fhir.oidc import SmartJwtValidator, SmartTokenValidationPolicy
from jmoraIs.smart_fhir.scopes import SmartScopeParser
from jmoraIs.smart_fhir.validation import SmartConfigurationParser


NOW = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)
ISSUER = "https://ehr.example.test"
AUDIENCE = "smart-client"
VERIFIER = "v" * 64


def _b64(value): return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


@pytest.fixture
def signing():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    numbers = private.public_key().public_numbers()
    jwk = {"kty": "RSA", "kid": "key-1", "alg": "RS256", "use": "sig",
           "n": _b64(numbers.n.to_bytes((numbers.n.bit_length() + 7) // 8, "big")),
           "e": _b64(numbers.e.to_bytes((numbers.e.bit_length() + 7) // 8, "big"))}
    keys = StaticSmartJwks.parse(json.dumps({"keys": [jwk]}).encode())
    return private, keys


def _token(private, *, subject="user-1", audience=AUDIENCE, issuer=ISSUER,
           expires=NOW + timedelta(minutes=10), not_before=NOW - timedelta(seconds=1),
           issued_at=NOW, nonce=None, headers=None):
    claims = {"iss": issuer, "aud": audience, "sub": subject, "iat": issued_at,
              "nbf": not_before, "exp": expires, "jti": "token-1"}
    if nonce is not None: claims["nonce"] = nonce
    return jwt.encode(claims, private, algorithm="RS256", headers=headers or {"kid": "key-1"})


def _validator(keys):
    return SmartJwtValidator(keys, SmartTokenValidationPolicy(ISSUER, AUDIENCE), clock=lambda: NOW)


def test_smart_and_oidc_discovery_are_parsed_without_transport():
    smart = {"authorization_endpoint": ISSUER + "/authorize", "token_endpoint": ISSUER + "/token",
             "grant_types_supported": ["authorization_code"], "code_challenge_methods_supported": ["S256"],
             "capabilities": ["launch-ehr", "sso-openid-connect"],
             "scopes_supported": ["openid", "launch/patient", "patient/*.read"]}
    oidc = {"issuer": ISSUER, "jwks_uri": ISSUER + "/jwks",
            "authorization_endpoint": ISSUER + "/authorize", "token_endpoint": ISSUER + "/token"}
    result = SmartConfigurationParser().parse(json.dumps(smart).encode(), json.dumps(oidc).encode())
    assert result.issuer == ISSUER and result.pkce_methods == ("S256",)
    smart["capabilities"].append("unsupported-extension")
    with pytest.raises(SmartConfigurationRejected):
        SmartConfigurationParser().parse(json.dumps(smart).encode(), json.dumps(oidc).encode())
    smart["capabilities"].pop(); oidc["jwks_uri"] = "https://attacker.example/jwks"
    with pytest.raises(SmartConfigurationRejected):
        SmartConfigurationParser().parse(json.dumps(smart).encode(), json.dumps(oidc).encode())


def test_pkce_s256_and_scope_launch_parsers_fail_closed():
    pkce = SmartPkceS256(); challenge = pkce.challenge(VERIFIER)
    assert pkce.verify(VERIFIER, challenge)
    with pytest.raises(SmartPkceRejected): pkce.verify(VERIFIER, challenge, "plain")
    scopes = SmartScopeParser().parse("openid fhirUser profile offline_access launch/patient patient/*.read patient/Observation.read patient/Condition.read")
    assert len(scopes) == 8
    for value in ("patient/Observation.write", "patient/Observation.*", "openid openid"):
        with pytest.raises(SmartScopeRejected): SmartScopeParser().parse(value)
    launch = SmartLaunchContextParser().parse({"patient": "Patient/opaque", "encounter": "Encounter/opaque"})
    assert launch.patient_reference == "Patient/opaque"
    with pytest.raises(SmartLaunchContextRejected): SmartLaunchContextParser().parse({"patient": "Patient/1", "custom": "x"})


def test_jwt_validation_accepts_signed_metadata_and_rejects_security_failures(signing):
    private, keys = signing; validator = _validator(keys)
    value = validator.validate(_token(private), SmartTokenType.ACCESS)
    assert value.subject == "user-1" and value.key_id == "key-1"
    assert not hasattr(value, "raw_token")
    invalid = [
        _token(private, expires=NOW - timedelta(seconds=60)),
        _token(private, issuer="https://wrong.example"),
        _token(private, audience="wrong-client"),
        _token(private, issued_at=NOW + timedelta(minutes=10), not_before=NOW - timedelta(seconds=1)),
        _token(private, not_before=NOW + timedelta(minutes=10)),
    ]
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    invalid.append(_token(other))
    for token in invalid:
        with pytest.raises(SmartTokenRejected): validator.validate(token, SmartTokenType.ACCESS)
    with pytest.raises(SmartTokenRejected):
        validator.validate(jwt.encode({"sub": "x"}, key="", algorithm="none", headers={"kid": "key-1"}), SmartTokenType.ACCESS)


def test_id_token_nonce_and_jwks_key_policy(signing):
    private, keys = signing; validator = _validator(keys)
    assert validator.validate(_token(private, nonce="nonce-1"), SmartTokenType.ID,
                              expected_nonce="nonce-1").nonce == "nonce-1"
    with pytest.raises(SmartTokenRejected):
        validator.validate(_token(private, nonce="wrong"), SmartTokenType.ID, expected_nonce="nonce-1")
    with pytest.raises(SmartConfigurationRejected): StaticSmartJwks.parse(b'{"keys":[]}')
    with pytest.raises(SmartConfigurationRejected):
        StaticSmartJwks.parse(b'{"keys":[{"kid":"x","alg":"none","kty":"RSA","use":"sig"}]}')


def test_authentication_flow_is_metadata_only_and_does_not_authorize_clinical_use(signing):
    private, keys = signing; audit = InMemorySmartAuthenticationAudit(); validator = _validator(keys)
    service = SmartFhirAuthenticationService(validator, validator, audit, issuer=ISSUER,
                                             policy_version="smart-policy-v1", clock=lambda: NOW)
    challenge = SmartPkceS256.challenge(VERIFIER)
    command = SmartAuthenticationCommand(_token(private), _token(private, nonce="nonce-1"),
        "openid launch/patient patient/Observation.read", {"patient": "Patient/opaque"},
        VERIFIER, challenge, "S256", "nonce-1", "corr-1")
    result = service.authenticate(command)
    assert result.policy_version == "smart-policy-v1"
    assert result.launch_context.patient_reference == "Patient/opaque"
    assert not hasattr(result, "authorized_operations") and not hasattr(result, "patient_context")
    event = audit.history("corr-1")[0]
    assert event.outcome == "SUCCESS" and command.access_token not in repr(event)

    missing_patient = SmartAuthenticationCommand(_token(private), None, "launch/patient", {},
        VERIFIER, challenge, "S256", None, "corr-2")
    with pytest.raises(SmartLaunchContextRejected): service.authenticate(missing_patient)
    assert audit.history("corr-2")[0].outcome == "FAILURE"
