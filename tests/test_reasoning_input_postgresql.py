import os
from dataclasses import replace
from uuid import uuid4
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine,text
from sqlalchemy.exc import DBAPIError
from jmoraIs.reasoning_input import *
from jmoraIs.terminology import (CodeSystem,MappingConfidence,MappingOutcome,MappingReviewStatus,MappingType,
    MappedClinicalConcept,PostgreSQLTerminologyMappingGovernanceRepository,TerminologyMappingGovernanceService)
from tests.test_terminology import concept
from tests.test_reasoning_input import NOW,draft
pytestmark=pytest.mark.integration
@pytest.fixture(scope="module")
def engine():
    url=os.getenv("JMORAIS_TEST_POSTGRES_URL")
    if not url:pytest.skip("JMORAIS_TEST_POSTGRES_URL is required")
    config=Config("alembic.ini");config.set_main_option("sqlalchemy.url",url);command.upgrade(config,"head")
    value=create_engine(url,future=True);yield value;value.dispose()
def test_postgresql_restart_reconstruction_and_append_only(engine):
    subject="pt_"+uuid4().hex*2
    repository=PostgreSQLClinicalReasoningInputRepository(engine);audit=PostgreSQLReasoningInputAuditAdapter(engine)
    service=ClinicalReasoningInputService(repository,audit,clock=lambda:NOW)
    first=service.build(replace(draft(),subject_reference=subject),actor_id="system",source_reference="assembly")
    second=service.mark_reviewed(subject,actor_id="physician",source_reference="review")
    restarted=PostgreSQLClinicalReasoningInputRepository(engine);restarted_audit=PostgreSQLReasoningInputAuditAdapter(engine)
    assert restarted.history(subject)==(first,second) and restarted.get(first.input_id)==first
    assert ClinicalReasoningInputQueryService(restarted).reconstruct(subject,1)==first
    assert len(restarted_audit.history(subject))==2
    with pytest.raises(DBAPIError),engine.begin() as connection:
        connection.execute(text("UPDATE clinical_reasoning_input_versions SET readiness='ALTERED' WHERE input_id=:id"),{"id":first.input_id})
    with pytest.raises(DBAPIError),engine.begin() as connection:
        connection.execute(text("DELETE FROM clinical_reasoning_input_versions WHERE input_id=:id"),{"id":first.input_id})
    with pytest.raises(DBAPIError),engine.begin() as connection:
        connection.execute(text("DELETE FROM clinical_reasoning_input_audit WHERE subject_reference=:id"),{"id":subject})

def test_stage4_to_stage8_exact_terminology_trace_survives_restart(engine):
    suffix=uuid4().hex;governance=PostgreSQLTerminologyMappingGovernanceRepository(engine)
    item=replace(concept("concept-"+suffix),version="terms-2026.1")
    mapped=MappedClinicalConcept(item.preferred_term,CodeSystem.ORTHOPEDIC,item.version,MappingOutcome.MAPPED,(item,),item.canonical_id,MappingConfidence.HIGH,False,("prov:"+suffix,))
    record=TerminologyMappingGovernanceService(governance,clock=lambda:NOW).persist(mapped,source_reference="state:"+suffix,target_concept_id=item.canonical_id,mapping_type=MappingType.EXACT,review_status=MappingReviewStatus.AUTO_MAPPED,review_required=False,mapping_method="deterministic",policy_version="terminology-mapping-v1")
    reference=governance.reference_for(record);subject="pt_"+suffix*2
    service=ClinicalReasoningInputService(PostgreSQLClinicalReasoningInputRepository(engine),PostgreSQLReasoningInputAuditAdapter(engine),clock=lambda:NOW,terminology_governance=governance)
    value=service.build(replace(draft(),subject_reference=subject,terminology_governance_references=(reference,)),actor_id="system",source_reference="stage4")
    del service,governance,mapped,record
    restarted=create_engine(os.environ["JMORAIS_TEST_POSTGRES_URL"],future=True)
    reread=PostgreSQLClinicalReasoningInputRepository(restarted).get(value.input_id);stored=reread.terminology_governance_references[0]
    exact=PostgreSQLTerminologyMappingGovernanceRepository(restarted).get_exact(stored)
    assert stored==reference and exact.governance_record_id==reference.governance_record_id
    assert exact.version==reference.record_version and exact.target_concept_id==reference.target_concept_id
    assert exact.terminology_version==reread.terminology_version and exact.integrity_hash==reference.integrity_hash
    restarted.dispose()
