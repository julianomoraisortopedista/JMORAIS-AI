from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class SmartFhirError(RuntimeError): pass
class SmartConfigurationRejected(SmartFhirError): pass
class SmartTokenRejected(SmartFhirError): pass
class SmartPkceRejected(SmartFhirError): pass
class SmartScopeRejected(SmartFhirError): pass
class SmartLaunchContextRejected(SmartFhirError): pass


class SmartTokenType(str,Enum): ACCESS="ACCESS";ID="ID"
class SmartScopeContext(str,Enum): IDENTITY="IDENTITY";LAUNCH="LAUNCH";PATIENT="PATIENT"


@dataclass(frozen=True)
class SmartEndpointConfiguration:
    issuer:str;authorization_endpoint:str;token_endpoint:str;jwks_uri:str
    grant_types:tuple[str,...];pkce_methods:tuple[str,...];capabilities:tuple[str,...]
    scopes_supported:tuple[str,...]


@dataclass(frozen=True)
class SmartJwk:
    key_id:str;algorithm:str;key_type:str;use:str;public_key:object


@dataclass(frozen=True)
class SmartScope:
    raw:str;context:SmartScopeContext;resource_type:str|None;permission:str


@dataclass(frozen=True)
class SmartLaunchContext:
    patient_reference:str|None=None;encounter_reference:str|None=None
    practitioner_reference:str|None=None;organization_reference:str|None=None
    user_reference:str|None=None


@dataclass(frozen=True)
class SmartValidatedToken:
    token_type:SmartTokenType;subject:str;issuer:str;audience:tuple[str,...]
    issued_at:datetime;not_before:datetime;expires_at:datetime;key_id:str
    algorithm:str;token_id:str|None;nonce:str|None


@dataclass(frozen=True)
class SmartAuthenticationResult:
    access_token:SmartValidatedToken;id_token:SmartValidatedToken|None
    scopes:tuple[SmartScope,...];launch_context:SmartLaunchContext
    correlation_id:str;policy_version:str


@dataclass(frozen=True)
class SmartAuthenticationAuditEvent:
    event_id:str;outcome:str;reason_code:str;correlation_id:str
    issuer:str;subject:str|None;policy_version:str;occurred_at:datetime
