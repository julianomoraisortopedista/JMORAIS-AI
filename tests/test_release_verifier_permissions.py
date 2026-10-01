"""Every direct Medical Document replay dependency must be globally read-only."""
import os
import pytest
from sqlalchemy import create_engine, text


def test_medical_document_replay_dependency_permissions():
    url = os.environ.get('JMORAIS_TEST_POSTGRES_URL')
    if not url:pytest.skip('isolated PostgreSQL required')
    engine = create_engine(url)
    try:
        with engine.connect() as c:
            for table in ('guideline_recommendation_set_references','orthopedic_assessment_set_references'):
                allowed = c.execute(text("SELECT has_table_privilege('jmorais_offline_replay_verifier',:table,'SELECT')"),dict(table=table)).scalar_one()
                assert allowed, 'OFFLINE_REPLAY_MISSING_SELECT:'+table
                assert not c.execute(text("SELECT has_table_privilege('jmorais_offline_replay_verifier',:table,'INSERT,UPDATE,DELETE,TRUNCATE')"),dict(table=table)).scalar_one()
            assert not c.execute(text("SELECT rolbypassrls FROM pg_roles WHERE rolname='jmorais_application_writer'")).scalar_one()
    finally:engine.dispose()
