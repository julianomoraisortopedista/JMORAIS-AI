from __future__ import annotations

from jmoraIs.application import EvidencePackage, ScientificDiscoveryResult
from jmoraIs.application.scientific_verification import (
    AuthoritativeReconciliationPipeline,
    ScientificVerificationInput,
)
from jmoraIs.evidence_ledger import AppendOnlyEvidenceLedger


class PrePackageEvidenceAccessError(RuntimeError):
    pass


class ScientificEvidenceEngine:
    """Public facade: discovery is untrusted; trusted output is package-only."""

    def __init__(self, verification_pipeline: AuthoritativeReconciliationPipeline):
        self._verification_pipeline = verification_pipeline

    def discover(self, request: ScientificVerificationInput) -> ScientificDiscoveryResult:
        return self._verification_pipeline.discover(request)

    def issue_trusted_evidence(
        self,
        request: ScientificVerificationInput,
        *,
        ledger: AppendOnlyEvidenceLedger,
        claim_id: str,
        support_ids: tuple[str, ...],
        pipeline_version: str,
    ) -> tuple[EvidencePackage, ...]:
        return self._verification_pipeline.issue_trusted(
            request,
            ledger=ledger,
            claim_id=claim_id,
            support_ids=support_ids,
            pipeline_version=pipeline_version,
        )

    def verify(self, _request: ScientificVerificationInput) -> None:
        raise PrePackageEvidenceAccessError(
            "pre-package verification results are internal; use discover or issue_trusted_evidence"
        )
