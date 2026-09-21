from __future__ import annotations

from jmoraIs.appraisal.governed import GovernedEvidence
from jmoraIs.application.scientific_citations import ScientificCitationQueryPort, ScientificCitationRecord
from jmoraIs.scientific_domain import PublicationStatus

from .domain import DocumentBoundaryRejected, DocumentEvidenceReference
from .ports import CanonicalCitationQueryPort, GovernedDocumentEvidencePort


class CanonicalDocumentCitationAdapter(CanonicalCitationQueryPort):
    """Reference-only projection from governed evidence to canonical scientific citation history."""

    _REVIEW_STATUSES = {
        PublicationStatus.EXPRESSION_OF_CONCERN.value,
        PublicationStatus.UNKNOWN.value,
    }

    def __init__(self, evidence: GovernedDocumentEvidencePort,
                 citations: ScientificCitationQueryPort) -> None:
        self._evidence = evidence
        self._citations = citations

    def get(self, evidence_id: str) -> DocumentEvidenceReference:
        if not isinstance(evidence_id, str) or not evidence_id.strip():
            raise DocumentBoundaryRejected("opaque governed evidence identifier is required")
        evidence = self._evidence.get(evidence_id)
        if not isinstance(evidence, GovernedEvidence):
            raise DocumentBoundaryRejected("canonical GovernedEvidence is required")
        record = self._citations.current_by_package(evidence.evidence_package_id)
        if not isinstance(record, ScientificCitationRecord):
            raise DocumentBoundaryRejected("canonical ScientificCitationRecord is required")
        if record.evidence_package_id != evidence.evidence_package_id:
            raise DocumentBoundaryRejected("scientific citation package linkage mismatch")
        if not record.provenance_references or not record.ledger_references or not record.verification_references:
            raise DocumentBoundaryRejected("scientific citation trust linkage is incomplete")
        if record.publication_status == PublicationStatus.RETRACTED.value:
            raise DocumentBoundaryRejected("retracted scientific citation is blocked")
        reference = record.vancouver_reference
        if not reference.rendered_text or not reference.citation_id or reference.package_id != record.evidence_package_id:
            raise DocumentBoundaryRejected("canonical Vancouver linkage is invalid")
        metadata = record.metadata
        return DocumentEvidenceReference(
            governed_evidence_id=evidence.governed_evidence_id,
            evidence_package_id=record.evidence_package_id,
            pmid=metadata.pmid,
            doi=metadata.doi,
            verification_status="VERIFIED",
            canonical_vancouver=reference.rendered_text,
            citation_reference_id=record.citation_record_id,
            provenance_references=record.provenance_references,
            publication_identity_id=record.publication_identity_id,
            pmcid=metadata.pmcid,
            vancouver_citation_id=reference.citation_id,
            formatter_version=reference.formatter_version,
            ledger_references=record.ledger_references,
            policy_version=record.policy_version,
            source_version=str(record.version),
            editorial_status=record.publication_status,
            review_required=record.publication_status in self._REVIEW_STATUSES,
        )
