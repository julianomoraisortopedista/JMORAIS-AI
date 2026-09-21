from __future__ import annotations

import json
from urllib.parse import urlparse

from .domain import SmartConfigurationRejected,SmartEndpointConfiguration


SUPPORTED_CAPABILITIES=frozenset({"launch-ehr","launch-standalone","client-public","sso-openid-connect",
    "context-passthrough-banner","context-passthrough-style"})


def _https(value,name):
    if not isinstance(value,str) or urlparse(value).scheme!="https" or not urlparse(value).netloc:
        raise SmartConfigurationRejected(f"{name} must be an absolute HTTPS URL")
    return value.rstrip("/")


class SmartConfigurationParser:
    """Deterministic parser for SMART and OIDC discovery documents; no transport."""
    def parse(self,smart_document:bytes,oidc_document:bytes)->SmartEndpointConfiguration:
        smart=self._json(smart_document);oidc=self._json(oidc_document)
        issuer=_https(oidc.get("issuer"),"issuer")
        authorization=_https(smart.get("authorization_endpoint") or oidc.get("authorization_endpoint"),"authorization_endpoint")
        token=_https(smart.get("token_endpoint") or oidc.get("token_endpoint"),"token_endpoint")
        jwks=_https(oidc.get("jwks_uri"),"jwks_uri")
        if any(urlparse(item).netloc!=urlparse(issuer).netloc for item in (authorization,token,jwks)):
            raise SmartConfigurationRejected("SMART endpoints must share the configured issuer authority")
        grants=tuple(smart.get("grant_types_supported") or oidc.get("grant_types_supported") or ())
        methods=tuple(smart.get("code_challenge_methods_supported") or ())
        capabilities=tuple(smart.get("capabilities") or ())
        scopes=tuple(smart.get("scopes_supported") or oidc.get("scopes_supported") or ())
        if "authorization_code" not in grants:raise SmartConfigurationRejected("authorization_code is required")
        if methods!=("S256",) and set(methods)!={"S256"}:raise SmartConfigurationRejected("only PKCE S256 is supported")
        unknown=set(capabilities)-SUPPORTED_CAPABILITIES
        if unknown:raise SmartConfigurationRejected("unsupported SMART capability")
        if not scopes or any(not isinstance(item,str) for item in scopes):raise SmartConfigurationRejected("SMART scopes are required")
        return SmartEndpointConfiguration(issuer,authorization,token,jwks,tuple(sorted(set(grants))),
            ("S256",),tuple(sorted(set(capabilities))),tuple(sorted(set(scopes))))

    @staticmethod
    def _json(value):
        if not isinstance(value,bytes):raise SmartConfigurationRejected("discovery input must be bytes")
        try:parsed=json.loads(value.decode("utf-8"))
        except (UnicodeDecodeError,json.JSONDecodeError) as exc:raise SmartConfigurationRejected("invalid discovery JSON") from exc
        if not isinstance(parsed,dict):raise SmartConfigurationRejected("discovery document must be an object")
        return parsed
