import os
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from jmoraIs.audit_defense import AuditDefenseService, PostgreSQLGovernedAuditTerminologyAdapter
from jmoraIs.terminology import (
    CodeSystem, MappingConfidence, MappingOutcome, MappingReviewStatus, MappingType,
    MappedClinicalConcept, PostgreSQLTerminologyMappingGovernanceRepository,
    PostgreSQLTerminologyRepository, TerminologyMappingGovernanceService,
)
from tests.test_terminology import NOW, concept

pytestmark = pytest.mark.integration


def test_postgresql_mapping_governance_restart_append_only_and_stage12_path():
    url = os.getenv("JMORAIS_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("JMORAIS_TEST_POSTGRES_URL is required")
    config = Config("alembic.ini"); config.set_main_option("sqlalchemy.url", url); command.upgrade(config, "head")
    suffix = uuid4().hex; engine = create_engine(url, future=True)
    item = concept(f"concept-governance-{suffix}", term=f"joint-{suffix}",
                   synonyms=(f"articulation-{suffix}",), code_value=f"ORTHO:{suffix}")
    concepts = PostgreSQLTerminologyRepository(engine); concepts.append(item.canonical_id, item)
    mapped = MappedClinicalConcept(item.preferred_term, CodeSystem.ORTHOPEDIC, item.version,
        MappingOutcome.MAPPED, (item,), item.canonical_id, MappingConfidence.HIGH, False,
        (f"terminology-source:{suffix}",))
    repository = PostgreSQLTerminologyMappingGovernanceRepository(engine)
    record = TerminologyMappingGovernanceService(repository, clock=lambda: NOW).persist(
        mapped, source_reference=f"source:{suffix}", target_concept_id=item.canonical_id,
        mapping_type=MappingType.EXACT, review_status=MappingReviewStatus.AUTO_MAPPED,
        review_required=False, mapping_method="deterministic-canonical-match",
        policy_version="terminology-mapping-v1")

    engine.dispose(); del concepts, repository, mapped
    restarted = create_engine(url, future=True)
    concepts_after = PostgreSQLTerminologyRepository(restarted)
    governance_after = PostgreSQLTerminologyMappingGovernanceRepository(restarted)
    adapter = PostgreSQLGovernedAuditTerminologyAdapter(
        concepts_after, governance_after, policy_version="terminology-mapping-v1")
    governed = adapter.get_governed(item.canonical_id)
    assert governed.concept == item and governed.governance_record_id == record.governance_record_id
    assert governed.mapping_type is MappingType.EXACT and governed.mapping_confidence is MappingConfidence.HIGH
    assert governed.provenance_references == (f"terminology-source:{suffix}",)
    AuditDefenseService._validate_terminology(
        SimpleNamespace(_terminology=adapter),
        (SimpleNamespace(terminology_concept_ids=(item.canonical_id,)),), item.version)

    with pytest.raises(DBAPIError), restarted.begin() as connection:
        connection.execute(text("UPDATE terminology_mapping_governance_versions SET policy_version='tampered' WHERE governance_record_id=:id"), {"id": record.governance_record_id})
    with pytest.raises(DBAPIError), restarted.begin() as connection:
        connection.execute(text("DELETE FROM terminology_mapping_governance_versions WHERE governance_record_id=:id"), {"id": record.governance_record_id})
    with pytest.raises(IntegrityError), restarted.begin() as connection:
        connection.execute(text("INSERT INTO terminology_mapping_governance_versions(governance_record_id,mapping_stream_id,source_reference,target_concept_id,terminology_version,mapping_type,mapping_confidence,review_status,review_required,policy_version,created_at,version,predecessor_record_id,integrity_hash,payload) SELECT :new_id,mapping_stream_id,source_reference,target_concept_id,terminology_version,mapping_type,mapping_confidence,review_status,review_required,policy_version,created_at,version,predecessor_record_id,integrity_hash,payload FROM terminology_mapping_governance_versions WHERE governance_record_id=:id"), {"new_id": "tmg_" + uuid4().hex, "id": record.governance_record_id})
    restarted.dispose()
