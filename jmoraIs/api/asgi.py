"""Fail-closed development/homologation ASGI composition root.

Run only on loopback with: uvicorn jmoraIs.api.asgi:app --host 127.0.0.1
"""
from __future__ import annotations

import os

from .app import ApiOperationalServices, ApiServices, create_app
from .security import CallerRole, PurposeOfUse, ReadinessCheck
from .security_infrastructure import (
    DeterministicDevelopmentAuthenticator, DevelopmentIdentity, InMemoryApiAccessAudit,
    InMemoryApiMetrics, StaticReadinessProbe,
)
from jmoraIs.infrastructure.api_observability import RedactingJsonLogAdapter
from .identity_security import CanonicalApiAuthorizationPolicy


def _identities() -> tuple[DevelopmentIdentity, ...]:
    token = os.getenv("JMORAIS_DEV_INTERNAL_TOKEN", "")
    if not token: return ()
    return (DevelopmentIdentity.from_token("local-internal-service", CallerRole.INTERNAL_SERVICE, token,
        (PurposeOfUse.INTERNAL_OPERATIONS, PurposeOfUse.SCIENTIFIC_VALIDATION), "api-access-v1"),)


# Domain query adapters are deliberately absent from this safe default. A real
# development/homologation composition root must inject them explicitly; until
# then readiness is NOT_READY and protected resource calls fail closed.
app = create_app(
    ApiServices(),
    ApiOperationalServices(
        authentication=DeterministicDevelopmentAuthenticator(_identities()),
        authorization=CanonicalApiAuthorizationPolicy(),
        readiness=StaticReadinessProbe((
            ReadinessCheck("postgresql", False, "NOT_CONFIGURED"),
            ReadinessCheck("migrations", False, "NOT_CONFIGURED"),
            ReadinessCheck("critical_dependencies", False, "NOT_CONFIGURED"),
        )),
        access_audit=InMemoryApiAccessAudit(),
        metrics=InMemoryApiMetrics(),
        structured_log=RedactingJsonLogAdapter(),
    ),
)
