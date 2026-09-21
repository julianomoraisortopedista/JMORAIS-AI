from __future__ import annotations

from jmoraIs.gateway_input import UpstreamArtifactReference
from jmoraIs.llm_human_review.domain import LLMHumanReviewRejected,UpstreamReviewConstraints
from jmoraIs.tenancy.context import current_tenant_context

from .domain import DefensePackage,LimitationSeverity


class AuditDefenseReviewGovernanceAdapter:
    """Owner-side projection of exact persisted Audit Defense review constraints."""

    def __init__(self,query,document_trace_port):
        self._query,self._documents=query,document_trace_port

    def constraints(self,reference):
        if not isinstance(reference,UpstreamArtifactReference) or reference.artifact_type!="AuditDefense" or reference.source_context!="audit_defense":
            raise LLMHumanReviewRejected("AuditDefense upstream reference is required")
        tenant=current_tenant_context()
        if reference.tenant_id!=tenant.tenant_id:raise LLMHumanReviewRejected("AuditDefense upstream tenant mismatch")
        try:
            persisted_reference=self._query.reference_from_upstream(reference)
            package=self._query.get_exact(persisted_reference)
            if not isinstance(package,DefensePackage) or package.stage11_document_reference is None:
                raise LLMHumanReviewRejected("final linked DefensePackage is required")
            self._documents.resolve_exact(package.stage11_document_reference)
        except LLMHumanReviewRejected:raise
        except Exception as exc:raise LLMHumanReviewRejected("AuditDefense upstream governance resolution failed") from exc
        if persisted_reference.tenant_id!=tenant.tenant_id or package.stage11_document_reference.tenant_id!=tenant.tenant_id:
            raise LLMHumanReviewRejected("AuditDefense governance tenant mismatch")
        if reference.policy_version!=persisted_reference.policy_version:
            raise LLMHumanReviewRejected("AuditDefense governance policy mismatch")
        critical=tuple(sorted({limitation.limitation_id for argument in package.defense.arguments
            for limitation in argument.limitations if limitation.severity is LimitationSeverity.CRITICAL}))
        return UpstreamReviewConstraints(critical,package.reviewer_id)
