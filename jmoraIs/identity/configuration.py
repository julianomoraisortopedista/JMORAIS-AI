from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OIDCProviderConfig:
    provider_id: str
    issuer: str
    audience: str
    discovery_url: str
    jwks_uri: str
    allowed_algorithms: tuple[str, ...]
    clock_skew_seconds: int
    required_claims: tuple[str, ...]
    role_claim: str
    organization_claim: str
    role_mapping: tuple[tuple[str, str], ...]
    token_type: str = "JWT"
    jwks_cache_seconds: int = 300
    policy_version: str = "iam-policy-v1"

    def __post_init__(self):
        if not all((self.provider_id, self.issuer, self.audience, self.discovery_url, self.jwks_uri,
                    self.allowed_algorithms, self.required_claims, self.role_claim,
                    self.organization_claim, self.role_mapping, self.policy_version)):
            raise ValueError("complete OIDC configuration is required")
        safe_prefixes = ("RS", "PS", "ES")
        if (any(item.lower() == "none" or not item.startswith(safe_prefixes)
                for item in self.allowed_algorithms) or self.clock_skew_seconds < 0):
            raise ValueError("unsafe OIDC algorithm or clock policy")
