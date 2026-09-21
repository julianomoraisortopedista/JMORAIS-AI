import os
from dataclasses import replace
from uuid import uuid4
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine,text
from sqlalchemy.exc import DBAPIError
from jmoraIs.terminology import *
from tests.test_terminology import NOW,TODAY,concept,source,version
pytestmark=pytest.mark.integration
@pytest.fixture(scope="module")
def engine():
    url=os.getenv("JMORAIS_TEST_POSTGRES_URL")
    if not url:pytest.skip("JMORAIS_TEST_POSTGRES_URL is required")
    config=Config("alembic.ini");config.set_main_option("sqlalchemy.url",url);command.upgrade(config,"head")
    value=create_engine(url,future=True);yield value;value.dispose()
def test_postgresql_restart_history_mapping_and_append_only(engine):
    suffix=uuid4().hex;repository=PostgreSQLTerminologyRepository(engine);audit=PostgreSQLTerminologyAuditAdapter(engine)
    term=concept(f"concept-{suffix}",term=f"test-joint-{suffix}",synonyms=(f"test-articulation-{suffix}",),code_value=f"ORTHO:{suffix}")
    release=replace(version(),version=f"1.0-{suffix}",version_id=f"version-{suffix}")
    term=replace(term,version=release.version,codes=(replace(term.codes[0],version=release.version),))
    repository.append(release.version_id,release);repository.append(term.canonical_id,term)
    service=ClinicalTerminologyService(repository,audit,DeterministicUcumAdapter(),clock=lambda:NOW)
    mapped=service.normalize_terminology(term.preferred_term,CodeSystem.ORTHOPEDIC,release.version)
    assert mapped.selected_concept_id==term.canonical_id
    retired=replace(term,status=TerminologyStatus.RETIRED,retirement_date=TODAY);repository.append(term.canonical_id,retired)
    restarted=PostgreSQLTerminologyRepository(engine);restarted_audit=PostgreSQLTerminologyAuditAdapter(engine)
    assert restarted.history(term.canonical_id)==(term,retired) and restarted.latest(term.canonical_id)==retired
    assert restarted.version(CodeSystem.ORTHOPEDIC,release.version)==release
    assert restarted_audit.history(term.preferred_term)
    with pytest.raises(DBAPIError),engine.begin() as connection:
        connection.execute(text("UPDATE terminology_records SET record_type='ALTERED' WHERE stream_id=:id"),{"id":term.canonical_id})
    with pytest.raises(DBAPIError),engine.begin() as connection:
        connection.execute(text("DELETE FROM terminology_records WHERE stream_id=:id"),{"id":term.canonical_id})
    with pytest.raises(DBAPIError),engine.begin() as connection:
        connection.execute(text("DELETE FROM terminology_audit_events WHERE subject_reference=:id"),{"id":term.preferred_term})
