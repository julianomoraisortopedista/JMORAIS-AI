import os
from dataclasses import replace
from uuid import uuid4
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine,text
from jmoraIs.guideline_engine import *
from tests.test_guideline_engine import NOW,guideline,ready_input,EvidenceQuery,Lifecycle,evidence
from jmoraIs.clinical import InMemoryGovernedDecisionAuditRepository,InMemoryReviewerAuthorizationAdapter,ReviewerIdentity,ReviewerRole,AuthorizedRecommendationReviewService,ReviewAuthorizationPolicy

def engine():
    url=os.getenv("JMORAIS_TEST_POSTGRES_URL")
    if not url:pytest.skip("JMORAIS_TEST_POSTGRES_URL is required")
    config=Config("alembic.ini");config.set_main_option("sqlalchemy.url",url);command.upgrade(config,"head")
    value=create_engine(url,future=True)
    with value.begin() as connection:connection.execute(text("TRUNCATE governed_guideline_source_versions,guideline_recommendation_versions,guideline_recommendation_audit RESTART IDENTITY CASCADE"))
    return value

def test_restart_query_and_stage9_generation_use_no_in_memory_guideline_state():
    database=engine();suffix=uuid4().hex;source=replace(guideline(),guideline_id=f"guideline-{suffix}")
    repository=PostgreSQLGuidelineSourceRepository(database)
    record=GovernedGuidelineSourceService(repository,clock=lambda:NOW).persist(source,appraisal_reference="appraisal-persisted",governance_status="ACTIVE")
    restarted=PostgreSQLGuidelineSourceRepository(create_engine(database.url,future=True))
    assert restarted.get(record.record_id)==record and restarted.history(record.guideline_id)==(record,)
    reasoning=ready_input();reasoning=replace(reasoning,applicable_guidelines=(replace(reasoning.applicable_guidelines[0],reference_id=record.guideline_id),))
    output=PostgreSQLRecommendationRepository(database);audit=PostgreSQLRecommendationAuditAdapter(database)
    review=AuthorizedRecommendationReviewService(InMemoryReviewerAuthorizationAdapter((ReviewerIdentity("reviewer",ReviewerRole.SENIOR_REVIEWER),)),InMemoryGovernedDecisionAuditRepository(),ReviewAuthorizationPolicy(),clock=lambda:NOW)
    generated=GuidelineRecommendationEngine(restarted,EvidenceQuery((evidence(),)),Lifecycle(),InMemoryGovernedTerminologyConceptQueryAdapter(()),output,audit,review,clock=lambda:NOW).create_recommendation_set(reasoning)
    assert generated.recommendations and PostgreSQLRecommendationRepository(create_engine(database.url,future=True)).latest(generated.subject_reference)==generated

def test_postgresql_guideline_sources_reject_update_delete_and_duplicate_version():
    database=engine();record=GovernedGuidelineSourceService(PostgreSQLGuidelineSourceRepository(database),clock=lambda:NOW).persist(guideline(),appraisal_reference="appraisal",governance_status="ACTIVE")
    with pytest.raises(Exception,match="append-only"),database.begin() as connection:connection.execute(text("UPDATE governed_guideline_source_versions SET governance_status='WITHDRAWN' WHERE record_id=:id"),{"id":record.record_id})
    with pytest.raises(Exception,match="append-only"),database.begin() as connection:connection.execute(text("DELETE FROM governed_guideline_source_versions WHERE record_id=:id"),{"id":record.record_id})
    with pytest.raises(Exception):
        PostgreSQLGuidelineSourceRepository(database).append(replace(record,record_id="duplicate",record_version=1))
