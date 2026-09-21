from dataclasses import replace
from pathlib import Path

import pytest

from jmoraIs.application.scientific_citations import citation_integrity_payload
from jmoraIs.evidence_ledger import LedgerEventType, hash_payload
from jmoraIs.medical_documents import CanonicalDocumentCitationAdapter, DocumentBoundaryRejected
from jmoraIs.scientific_domain import PublicationStatus
from tests.test_guideline_engine import EvidenceQuery, evidence
from tests.test_scientific_citation_persistence import setup as scientific_setup


def adapter(status=PublicationStatus.RELIABLE.value):
    article, _, _, _, package, vancouver, _, service = scientific_setup(status)
    service.issue(package_id=package.package_id, article=article, vancouver_reference=vancouver)
    governed = replace(evidence(), evidence_package_id=package.package_id)
    return CanonicalDocumentCitationAdapter(EvidenceQuery((governed,)), service), governed, service


def test_projects_exact_canonical_scientific_reference_without_payload_duplication():
    projection, governed, service = adapter()
    record = service.current_by_package(governed.evidence_package_id)
    result = projection.get(governed.governed_evidence_id)
    assert result.governed_evidence_id == governed.governed_evidence_id
    assert result.evidence_package_id == record.evidence_package_id
    assert result.publication_identity_id == record.publication_identity_id
    assert (result.pmid, result.doi, result.pmcid) == (record.metadata.pmid, record.metadata.doi, record.metadata.pmcid)
    assert result.canonical_vancouver == record.vancouver_reference.rendered_text
    assert result.vancouver_citation_id == record.vancouver_reference.citation_id
    assert result.formatter_version == record.vancouver_reference.formatter_version
    assert result.citation_reference_id == record.citation_record_id
    assert result.ledger_references == record.ledger_references
    assert result.policy_version == record.policy_version and result.source_version == str(record.version)
    assert result.verification_status == "VERIFIED" and not result.review_required


@pytest.mark.parametrize("status", [PublicationStatus.CORRECTED.value,
    PublicationStatus.EXPRESSION_OF_CONCERN.value, PublicationStatus.UNKNOWN.value])
def test_editorial_governance_is_preserved(status):
    projection, governed, _ = adapter(status)
    result = projection.get(governed.governed_evidence_id)
    assert result.editorial_status == status
    assert result.review_required is (status != PublicationStatus.CORRECTED.value)


def test_nonexistent_governed_evidence_and_malformed_identifier_fail_closed():
    projection, _, _ = adapter()
    with pytest.raises(DocumentBoundaryRejected): projection.get("missing")
    with pytest.raises(DocumentBoundaryRejected): projection.get("")


class InvalidScientificQuery:
    def __init__(self, value): self.value = value
    def current_by_package(self, _package_id):
        if isinstance(self.value, Exception): raise self.value
        return self.value


def test_nonexistent_or_invalid_scientific_record_is_never_projected():
    governed = evidence()
    with pytest.raises(DocumentBoundaryRejected):
        CanonicalDocumentCitationAdapter(EvidenceQuery((governed,)), InvalidScientificQuery(None)).get(governed.governed_evidence_id)
    with pytest.raises(RuntimeError, match="integrity"):
        CanonicalDocumentCitationAdapter(EvidenceQuery((governed,)), InvalidScientificQuery(RuntimeError("integrity invalid"))).get(governed.governed_evidence_id)


def test_package_mismatch_and_incomplete_linkage_fail_closed():
    projection, governed, service = adapter(); record = service.current_by_package(governed.evidence_package_id)
    with pytest.raises(DocumentBoundaryRejected, match="mismatch"):
        CanonicalDocumentCitationAdapter(EvidenceQuery((governed,)), InvalidScientificQuery(replace(record, evidence_package_id="other"))).get(governed.governed_evidence_id)
    with pytest.raises(DocumentBoundaryRejected, match="incomplete"):
        CanonicalDocumentCitationAdapter(EvidenceQuery((governed,)), InvalidScientificQuery(replace(record, provenance_references=()))).get(governed.governed_evidence_id)


def test_altered_or_fabricated_vancouver_linkage_fails_closed():
    projection, governed, service = adapter(); record = service.current_by_package(governed.evidence_package_id)
    altered = replace(record, vancouver_reference=replace(record.vancouver_reference, rendered_text=""))
    with pytest.raises(DocumentBoundaryRejected, match="Vancouver"):
        CanonicalDocumentCitationAdapter(EvidenceQuery((governed,)), InvalidScientificQuery(altered)).get(governed.governed_evidence_id)
    fabricated = replace(record, vancouver_reference=replace(record.vancouver_reference, citation_id=""))
    with pytest.raises(DocumentBoundaryRejected, match="Vancouver"):
        CanonicalDocumentCitationAdapter(EvidenceQuery((governed,)), InvalidScientificQuery(fabricated)).get(governed.governed_evidence_id)


def test_revoked_package_is_rejected_through_canonical_scientific_query():
    article, ledger, support, _, package, vancouver, _, service = scientific_setup()
    service.issue(package_id=package.package_id, article=article, vancouver_reference=vancouver)
    governed = replace(evidence(), evidence_package_id=package.package_id)
    ledger.append_lifecycle_event(claim_id="claim-1", event_type=LedgerEventType.RETRACTION,
                                  target_support_id=support.support_id, occurred_at=package.created_at)
    with pytest.raises(Exception, match="currently valid"):
        CanonicalDocumentCitationAdapter(EvidenceQuery((governed,)), service).get(governed.governed_evidence_id)


@pytest.mark.parametrize("change", [
    {"integrity_hash": "invalid"},
    {"verification_references": ("invalid",)},
    {"ledger_references": ("invalid",)},
])
def test_invalid_persisted_scientific_trust_state_is_rejected(change):
    article, _, _, _, package, vancouver, repository, service = scientific_setup()
    record = service.issue(package_id=package.package_id, article=article, vancouver_reference=vancouver)
    repository._records[0] = replace(record, **change)
    governed = replace(evidence(), evidence_package_id=package.package_id)
    with pytest.raises(Exception):
        CanonicalDocumentCitationAdapter(EvidenceQuery((governed,)), service).get(governed.governed_evidence_id)


def test_persisted_retracted_status_is_rejected_even_with_valid_record_hash():
    article, _, _, _, package, vancouver, repository, service = scientific_setup()
    record = service.issue(package_id=package.package_id, article=article, vancouver_reference=vancouver)
    retracted = replace(record, publication_status=PublicationStatus.RETRACTED.value, integrity_hash="")
    retracted = replace(retracted, integrity_hash=hash_payload(citation_integrity_payload(retracted)))
    repository._records[0] = retracted
    governed = replace(evidence(), evidence_package_id=package.package_id)
    with pytest.raises(Exception, match="retracted"):
        CanonicalDocumentCitationAdapter(EvidenceQuery((governed,)), service).get(governed.governed_evidence_id)


def test_architecture_is_a_reference_only_scientific_projection():
    root = Path(__file__).parents[1]
    adapter_source = (root / "jmoraIs/medical_documents/citation_projection.py").read_text()
    engine_source = (root / "jmoraIs/medical_documents/application.py").read_text()
    assert "ScientificCitationQueryPort" in adapter_source
    assert all(token not in adapter_source for token in ("connect.pubmed", "connect.crossref", "OpenAlex", "StrictVancouverFormatter", "jmoraIs.db", "evaluation"))
    assert "CanonicalCitationQueryPort" not in engine_source and "self._citations.get" in engine_source
