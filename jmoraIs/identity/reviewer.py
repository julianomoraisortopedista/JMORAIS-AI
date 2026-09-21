from __future__ import annotations

from .domain import AuthenticatedPrincipal, IdentityAuthorizationRejected, IdentityLinkStatus, PrincipalType


class AuthenticatedReviewerResolver:
    """Links OIDC principals to the existing canonical ReviewerIdentity repository."""
    def __init__(self, links, reviewers): self._links, self._reviewers = links, reviewers
    def resolve(self, principal: AuthenticatedPrincipal):
        if principal.principal_type is not PrincipalType.HUMAN:
            raise IdentityAuthorizationRejected("service principal is not a reviewer")
        link = self._links.get(principal.identity_provider, principal.external_subject)
        if link is None or link.status is not IdentityLinkStatus.ACTIVE or not link.reviewer_id:
            raise IdentityAuthorizationRejected("active reviewer identity link is required")
        reviewer = self._reviewers.resolve(link.reviewer_id)
        if reviewer is None or not self._reviewers.may_review(reviewer):
            raise IdentityAuthorizationRejected("linked reviewer is not authorized")
        if reviewer.organization_id != principal.organization_id:
            raise IdentityAuthorizationRejected("reviewer organization does not match principal")
        if reviewer.tenant_id != principal.tenant_id:
            raise IdentityAuthorizationRejected("reviewer tenant does not match principal")
        return reviewer
