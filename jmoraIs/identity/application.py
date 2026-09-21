from __future__ import annotations

from uuid import uuid4

from .domain import ExternalIdentityLink, IdentityLinkStatus, IdentitySecurityEvent, IdentitySecurityEventType


class IdentityLinkService:
    def __init__(self, repository, audit, *, clock): self._repository, self._audit, self._clock = repository, audit, clock
    def create(self, link: ExternalIdentityLink, *, correlation_id: str):
        self._repository.create(link)
        self._event(IdentitySecurityEventType.IDENTITY_LINK_CREATED, link, correlation_id, "LINK_CREATED")
        return link
    def suspend(self, provider, subject, *, correlation_id):
        link = self._repository.set_status(provider, subject, IdentityLinkStatus.SUSPENDED, self._clock())
        self._event(IdentitySecurityEventType.IDENTITY_SUSPENDED, link, correlation_id, "LINK_SUSPENDED")
        return link
    def disable(self, provider, subject, *, correlation_id):
        link = self._repository.set_status(provider, subject, IdentityLinkStatus.DISABLED, self._clock())
        self._event(IdentitySecurityEventType.IDENTITY_SUSPENDED, link, correlation_id, "LINK_DISABLED")
        return link
    def _event(self, kind, link, correlation, reason):
        self._audit.append(IdentitySecurityEvent("iam_" + uuid4().hex, kind, link.principal_id,
            link.provider, correlation, reason, link.policy_version, self._clock()))
