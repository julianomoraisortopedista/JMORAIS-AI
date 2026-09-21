from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from jmoraIs.identity.domain import (
    IdentityAuthenticationRejected, IdentityAuthorizationRejected, IdentitySecurityEvent,
    IdentitySecurityEventType,
)

from .security import CallerContext, CallerCredentials, CallerRole, PurposeOfUse, ReadinessCheck


class ExternalIdentityApiAuthenticator:
    homologation_safe = True
    def __init__(self, provider, tenant_resolution=None, tenant_authorization=None):
        self._provider, self._tenant_resolution, self._tenant_authorization = \
            provider, tenant_resolution, tenant_authorization
    def authenticate(self, credentials: CallerCredentials, correlation_id: str) -> CallerContext:
        principal = self._provider.validate(credentials.bearer_token, correlation_id)
        try: purpose = PurposeOfUse(credentials.purpose)
        except (ValueError, TypeError) as exc: raise IdentityAuthenticationRejected("a valid purpose is required") from exc
        if purpose.value not in principal.allowed_purposes:
            raise IdentityAuthenticationRejected("purpose is not authorized for principal")
        try: roles = tuple(CallerRole(item) for item in principal.roles)
        except ValueError as exc: raise IdentityAuthenticationRejected("principal role mapping is invalid") from exc
        if not roles: raise IdentityAuthenticationRejected("principal has no canonical role")
        if self._tenant_resolution is not None and self._tenant_authorization is not None:
            tenant = self._tenant_resolution.resolve(principal.organization_id,
                principal_id=principal.principal_id, correlation_id=correlation_id,
                policy_version=principal.policy_version)
            context = self._tenant_authorization.authorize(tenant=tenant,
                principal_id=principal.principal_id, organization_id=principal.organization_id,
                role=roles[0].value, purpose=purpose.value, policy_version=principal.policy_version,
                correlation_id=correlation_id)
            if context.tenant_id != principal.tenant_id:
                raise IdentityAuthenticationRejected("identity tenant association is invalid")
        return CallerContext(principal.principal_id, roles[0], purpose, correlation_id,
            principal.policy_version, roles, principal.organization_id, principal.tenant_id,
            principal.principal_type.value, principal.scoped_permissions)
    def readiness(self) -> ReadinessCheck: return self._provider.readiness()


class CanonicalApiAuthorizationPolicy:
    _ROLES = {
        "READINESS": {CallerRole.INTERNAL_SERVICE, CallerRole.ADMINISTRATOR},
        "VERSION": set(CallerRole),
        "REASONING_INPUT": set(CallerRole),
        "GOVERNED_EVIDENCE": set(CallerRole),
        "GUIDELINE": set(CallerRole),
        "ORTHOPEDIC": {CallerRole.CLINICAL_REVIEWER, CallerRole.ADMINISTRATOR},
        "MEDICAL_DOCUMENT": {CallerRole.CLINICAL_REVIEWER, CallerRole.ADMINISTRATOR},
        "AUDIT_DEFENSE": {CallerRole.CLINICAL_REVIEWER, CallerRole.ADMINISTRATOR},
    }
    _PURPOSES = {
        "READINESS": {PurposeOfUse.INTERNAL_OPERATIONS, PurposeOfUse.ADMINISTRATION},
        "VERSION": set(PurposeOfUse),
        "REASONING_INPUT": set(PurposeOfUse),
        "GOVERNED_EVIDENCE": set(PurposeOfUse),
        "GUIDELINE": set(PurposeOfUse),
        "ORTHOPEDIC": {PurposeOfUse.CLINICAL_REVIEW, PurposeOfUse.ADMINISTRATION},
        "MEDICAL_DOCUMENT": {PurposeOfUse.CLINICAL_REVIEW, PurposeOfUse.ADMINISTRATION},
        "AUDIT_DEFENSE": {PurposeOfUse.CLINICAL_REVIEW, PurposeOfUse.ADMINISTRATION},
    }
    def __init__(self, audit=None, *, clock=None, provider="internal-api"):
        self._audit, self._provider = audit, provider
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def authorize(self, caller: CallerContext, resource_class: str) -> None:
        roles = set(caller.roles or (caller.role,))
        if not caller.organization_id or not caller.policy_version or resource_class not in self._ROLES:
            self._deny(caller, "INVALID_AUTHORIZATION_CONTEXT")
        if not roles.intersection(self._ROLES[resource_class]) or caller.purpose not in self._PURPOSES[resource_class]:
            self._deny(caller, "ROLE_OR_PURPOSE_DENIED")
        if caller.principal_type == "SERVICE" and CallerRole.CLINICAL_REVIEWER in roles:
            self._deny(caller, "SERVICE_REVIEWER_PRIVILEGE_DENIED")

    def readiness(self) -> ReadinessCheck:
        return ReadinessCheck("authorization_policy", True, "AVAILABLE")

    def _deny(self, caller: CallerContext, reason: str) -> None:
        if self._audit is not None:
            self._audit.append(IdentitySecurityEvent(
                "iam_" + uuid4().hex, IdentitySecurityEventType.AUTHORIZATION_DENIAL,
                caller.caller_id, self._provider, caller.correlation_id, reason,
                caller.policy_version, self._clock()))
        raise IdentityAuthorizationRejected("authorization denied")
