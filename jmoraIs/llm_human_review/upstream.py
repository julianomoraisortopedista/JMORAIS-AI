from __future__ import annotations

from jmoraIs.medical_documents import ValidationSeverity

from .domain import LLMHumanReviewRejected, UpstreamReviewConstraints


class MedicalDocumentReviewGovernanceAdapter:
    """Projects persisted document governance without copying its clinical data."""
    def __init__(self, documents):
        self._documents = documents

    def constraints(self, reference):
        if reference.artifact_type != "MedicalDocument":
            raise LLMHumanReviewRejected("unsupported persisted upstream artifact")
        history = self._documents.history(reference.artifact_id)
        version = next((item for item in history if item.version == reference.artifact_version), None)
        if version is None or version.version_id != reference.version_id:
            raise LLMHumanReviewRejected("persisted upstream artifact linkage is invalid")
        critical = tuple(sorted({issue.code for issue in version.document.validation.issues if issue.severity is ValidationSeverity.CRITICAL}))
        return UpstreamReviewConstraints(critical, version.reviewer_id)


class UpstreamReviewGovernanceRouter:
    """Dispatches by declared artifact type while keeping review policy generic."""
    def __init__(self,adapters):self._adapters=dict(adapters)
    def constraints(self,reference):
        adapter=self._adapters.get(getattr(reference,"artifact_type",None))
        if adapter is None:raise LLMHumanReviewRejected("unsupported persisted upstream artifact")
        return adapter.constraints(reference)
