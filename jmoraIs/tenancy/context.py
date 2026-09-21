from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from uuid import uuid4

from .domain import (
    MissingTenantContext, TenantAuthorizationRejected, TenantContext, TenantError,
    TenantSecurityEvent, TenantSecurityEventType,
)


_CURRENT: ContextVar[TenantContext | None] = ContextVar("jmorais_tenant_context", default=None)


def current_tenant_context() -> TenantContext:
    value = _CURRENT.get()
    if value is None:
        raise MissingTenantContext("tenant context is required")
    return value


class TenantContextBinder:
    def __init__(self, audit=None, *, clock=None):
        self._audit = audit
        self._clock = clock or (lambda: datetime.now(timezone.utc))
    @contextmanager
    def bind_tenant(self, context: TenantContext):
        token = _CURRENT.set(context)
        try: yield context
        finally: _CURRENT.reset(token)

    @contextmanager
    def bind(self, caller):
        try:
            context = TenantContext(caller.tenant_id, caller.organization_id, caller.caller_id,
                caller.role.value, caller.purpose.value, caller.policy_version, caller.correlation_id)
        except (AttributeError, TenantError) as exc:
            if self._audit is not None:
                self._audit.append(TenantSecurityEvent("tenant_" + uuid4().hex,
                    TenantSecurityEventType.MISSING_CONTEXT, None,
                    getattr(caller, "organization_id", None), getattr(caller, "caller_id", None),
                    getattr(caller, "correlation_id", "unresolved"), "MALFORMED_TENANT_CONTEXT",
                    getattr(caller, "policy_version", "unresolved"), self._clock()))
            raise TenantAuthorizationRejected("complete tenant context is required") from exc
        with self.bind_tenant(context): yield context
