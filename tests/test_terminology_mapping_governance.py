from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone

import pytest

from jmoraIs.audit_defense import AuditDefenseBoundaryRejected, PostgreSQLGovernedAuditTerminologyAdapter
from jmoraIs.terminology import (
    CodeSystem, InMemoryTerminologyMappingGovernanceRepository, InMemoryTerminologyRepository,
    InvalidTerminologyRecord, MappingConfidence, MappingOutcome, MappingReviewStatus, MappingType,
    MappedClinicalConcept, TerminologyMappingGovernanceService, TerminologyStatus,
    TerminologyVersionConflict, mapping_governance_integrity_hash,
)
from tests.test_terminology import concept

NOW = datetime(2026, 8, 12, tzinfo=timezone.utc)
POLICY = "terminology-mapping-v1"


def mapping(item=None, *, confidence=MappingConfidence.HIGH, outcome=MappingOutcome.MAPPED,
            candidates=None, selected=None, provenance=("mapping:canonical",)):
    item = item or concept()
    values = (item,) if candidates is None else candidates
    return MappedClinicalConcept(
        item.preferred_term, CodeSystem.ORTHOPEDIC, item.version, outcome, values,
        item.canonical_id if selected is None and outcome is MappingOutcome.MAPPED else selected,
        confidence, outcome is MappingOutcome.REVIEW_REQUIRED, provenance,
    )


def persisted(item=None, **overrides):
    item = item or concept()
    concepts = InMemoryTerminologyRepository(); concepts.append(item.canonical_id, item)
    governance = InMemoryTerminologyMappingGovernanceRepository()
    values = dict(source_reference="source:knee", target_concept_id=item.canonical_id,
                  mapping_type=MappingType.EXACT, review_status=MappingReviewStatus.AUTO_MAPPED,
                  review_required=False, mapping_method="deterministic-canonical-match",
                  policy_version=POLICY)
    values.update(overrides)
    record = TerminologyMappingGovernanceService(governance, clock=lambda: NOW).persist(mapping(item), **values)
    return item, concepts, governance, record


def test_mapping_governance_is_separate_immutable_and_integrity_protected():
    item, _, _, record = persisted()
    assert "mapping_confidence" not in item.__dataclass_fields__
    assert record.mapping_type is MappingType.EXACT and record.mapping_confidence is MappingConfidence.HIGH
    assert record.review_status is MappingReviewStatus.AUTO_MAPPED and not record.review_required
    assert record.integrity_hash == mapping_governance_integrity_hash(record)
    with pytest.raises(FrozenInstanceError): record.policy_version = "changed"


def test_governance_never_fabricates_missing_provenance():
    repository = InMemoryTerminologyMappingGovernanceRepository()
    with pytest.raises(InvalidTerminologyRecord, match="provenance"):
        TerminologyMappingGovernanceService(repository, clock=lambda: NOW).persist(
            mapping(provenance=()), source_reference="source:knee", target_concept_id="concept-knee",
            mapping_type=MappingType.EXACT, review_status=MappingReviewStatus.AUTO_MAPPED,
            review_required=False, mapping_method="deterministic", policy_version=POLICY)


def test_restart_projection_preserves_complete_governance_and_releases_only_eligible_concept():
    item, concepts, governance, record = persisted()
    adapter = PostgreSQLGovernedAuditTerminologyAdapter(concepts, governance, policy_version=POLICY)
    governed = adapter.get_governed(item.canonical_id)
    assert governed.concept == item and governed.governance_record_id == record.governance_record_id
    assert governed.mapping_type is MappingType.EXACT and governed.mapping_confidence is MappingConfidence.HIGH
    assert governed.policy_version == POLICY and governed.provenance_references == ("mapping:canonical",)
    assert adapter.get(item.canonical_id) == item
    assert governance.get(record.governance_record_id) == record
    assert governance.by_source_reference("source:knee") == (record,)


@pytest.mark.parametrize("changes", [
    {"mapping_type": MappingType.RELATED, "review_status": MappingReviewStatus.REVIEW_REQUIRED, "review_required": True},
    {"mapping_confidence": MappingConfidence.LOW},
    {"review_status": MappingReviewStatus.REVIEW_REQUIRED, "review_required": True},
    {"review_status": MappingReviewStatus.REJECTED, "review_required": True, "reviewer_reference": "reviewer:1"},
])
def test_uncertain_or_rejected_governance_fails_closed(changes):
    item, concepts, governance, record = persisted()
    changed = replace(record, governance_record_id=record.governance_record_id + "x", version=2,
                      predecessor_record_id=record.governance_record_id, **changes, integrity_hash="pending")
    changed = replace(changed, integrity_hash=mapping_governance_integrity_hash(changed)); governance.append(changed)
    adapter = PostgreSQLGovernedAuditTerminologyAdapter(concepts, governance, policy_version=POLICY)
    assert adapter.get_governed(item.canonical_id).review_status is changed.review_status
    with pytest.raises(AuditDefenseBoundaryRejected): adapter.get(item.canonical_id)


@pytest.mark.parametrize("status,successor", [
    (TerminologyStatus.DEPRECATED, None), (TerminologyStatus.SUPERSEDED, "concept:new")])
def test_concept_lifecycle_is_independent_and_ineligible(status, successor):
    item = concept(status=status, superseded_by=successor)
    _, concepts, governance, _ = persisted(item)
    adapter = PostgreSQLGovernedAuditTerminologyAdapter(concepts, governance, policy_version=POLICY)
    assert adapter.get_governed(item.canonical_id).concept.status is status
    with pytest.raises(AuditDefenseBoundaryRejected): adapter.get(item.canonical_id)


def test_missing_mismatch_corruption_policy_and_chain_fail_closed():
    item, concepts, governance, record = persisted()
    adapter = PostgreSQLGovernedAuditTerminologyAdapter(concepts, governance, policy_version=POLICY)
    with pytest.raises(AuditDefenseBoundaryRejected): adapter.get("missing")
    no_governance = PostgreSQLGovernedAuditTerminologyAdapter(concepts, InMemoryTerminologyMappingGovernanceRepository(), policy_version=POLICY)
    with pytest.raises(AuditDefenseBoundaryRejected): no_governance.get(item.canonical_id)
    with pytest.raises(AuditDefenseBoundaryRejected): PostgreSQLGovernedAuditTerminologyAdapter(concepts, governance, policy_version="new-policy").get(item.canonical_id)
    governance._items[record.governance_record_id] = replace(record, integrity_hash="0" * 64)
    with pytest.raises(AuditDefenseBoundaryRejected): adapter.get(item.canonical_id)


def test_policy_change_creates_a_new_version_without_rewriting_history():
    item, concepts, governance, first = persisted()
    second = TerminologyMappingGovernanceService(governance, clock=lambda: NOW).persist(
        mapping(item), source_reference="source:knee", target_concept_id=item.canonical_id,
        mapping_type=MappingType.EQUIVALENT, review_status=MappingReviewStatus.REVIEWED,
        review_required=False, reviewer_reference="reviewer:terminology",
        mapping_method="governed-review", policy_version="terminology-mapping-v2")
    assert governance.history_by_concept(item.canonical_id) == (first, second)
    assert second.version == 2 and second.predecessor_record_id == first.governance_record_id
    assert first.policy_version == POLICY
    with pytest.raises(AuditDefenseBoundaryRejected):
        PostgreSQLGovernedAuditTerminologyAdapter(concepts, governance, policy_version=POLICY).get(item.canonical_id)
    assert PostgreSQLGovernedAuditTerminologyAdapter(
        concepts, governance, policy_version="terminology-mapping-v2").get(item.canonical_id) == item


def test_duplicate_and_invalid_predecessor_are_rejected():
    _, _, governance, record = persisted()
    with pytest.raises(TerminologyVersionConflict): governance.append(record)
    invalid = replace(record, governance_record_id=record.governance_record_id + "x", version=2,
                      predecessor_record_id="wrong", integrity_hash="pending")
    invalid = replace(invalid, integrity_hash=mapping_governance_integrity_hash(invalid))
    with pytest.raises(TerminologyVersionConflict): governance.append(invalid)
