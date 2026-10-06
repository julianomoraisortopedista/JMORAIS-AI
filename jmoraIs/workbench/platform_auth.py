"""Platform-mode authentication for the evidence workbench, delegated to the existing IAM.

Same rules as the clinical workspace endpoints: an OIDC bearer is required, caller-
supplied tenant/role/organization headers are refused, the purpose is fixed to
CLINICAL_REVIEW, the existing authentication and authorization services decide, and
only HUMAN clinical reviewers are accepted. Nothing here weakens or bypasses IAM.
"""
from __future__ import annotations

from typing import Callable
from uuid import uuid4

from fastapi import Request

from jmoraIs.api.security import CallerContext, CallerCredentials, CallerRole, PurposeOfUse
from jmoraIs.workbench.app import WorkbenchAuthError

FORBIDDEN_HEADERS = ("x-tenant-id", "x-organization-id", "x-role", "x-roles", "x-authorization-state")


def iam_authenticator(operations, resource_class: str = "WORKSPACE_READ") -> Callable[[Request], str]:
    def authenticate(request: Request) -> str:
        authorization = request.headers.get("authorization", "")
        if not authorization.startswith("Bearer ") or not authorization[7:].strip():
            raise WorkbenchAuthError(401)
        if any(name in request.headers for name in FORBIDDEN_HEADERS):
            raise WorkbenchAuthError(403)
        purpose = request.headers.get("x-purpose", "")
        if purpose and purpose != PurposeOfUse.CLINICAL_REVIEW.value:
            raise WorkbenchAuthError(403)
        correlation = "evid-" + uuid4().hex
        try:
            caller = operations.authentication.authenticate(
                CallerCredentials(authorization[7:].strip(), PurposeOfUse.CLINICAL_REVIEW.value), correlation)
        except Exception as exc:
            raise WorkbenchAuthError(401) from exc
        if not isinstance(caller, CallerContext) or not caller.caller_id:
            raise WorkbenchAuthError(401)
        try:
            operations.authorization.authorize(caller, resource_class)
        except Exception as exc:
            raise WorkbenchAuthError(403) from exc
        if caller.principal_type != "HUMAN" or caller.role is not CallerRole.CLINICAL_REVIEWER:
            raise WorkbenchAuthError(403)
        return caller.caller_id
    return authenticate
