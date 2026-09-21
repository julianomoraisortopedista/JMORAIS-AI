import os
from uuid import uuid4
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine,text
from sqlalchemy.exc import DBAPIError

from jmoraIs.clinical_state import *
from tests.test_clinical_state import rich_context
from tests.test_patient_context_domain import NOW

pytestmark=pytest.mark.integration
@pytest.fixture(scope="module")
def engine():
    url=os.getenv("JMORAIS_TEST_POSTGRES_URL")
    if not url:pytest.skip("JMORAIS_TEST_POSTGRES_URL is required")
    config=Config("alembic.ini");config.set_main_option("sqlalchemy.url",url);command.upgrade(config,"head")
    value=create_engine(url,future=True);yield value;value.dispose()

def test_postgresql_state_and_audit_recover_after_restart_and_are_append_only(engine):
    suffix=uuid4().hex;ctx=rich_context(f"state-context-{suffix}")
    states=PostgreSQLClinicalStateRepository(engine);audit=PostgreSQLClinicalStateAuditAdapter(engine)
    app=PatientClinicalStateService(AuthorizedPatientContextQueryAdapter(lambda patient:(ctx,)),states,audit,DeterministicClinicalNormalizer(),clock=lambda:NOW)
    first=app.build_current_state(ctx.patient_identity.patient_id)
    second=app.request_review(ctx.patient_identity.patient_id,actor_id="reviewer",source_event_id="request",provenance="review:request")
    restarted=PostgreSQLClinicalStateRepository(engine);restarted_audit=PostgreSQLClinicalStateAuditAdapter(engine)
    assert restarted.history(ctx.patient_identity.patient_id)==(first,second)
    assert restarted.latest(ctx.patient_identity.patient_id)==second
    assert restarted.at(ctx.patient_identity.patient_id,first.as_of) in (first,second)
    assert len(restarted_audit.history(ctx.patient_identity.patient_id))==2
    with pytest.raises(DBAPIError),engine.begin() as connection:
        connection.execute(text("UPDATE patient_clinical_state_versions SET review_status='ALTERED' WHERE state_id=:id"),{"id":first.state_id})
    with pytest.raises(DBAPIError),engine.begin() as connection:
        connection.execute(text("DELETE FROM patient_clinical_state_versions WHERE state_id=:id"),{"id":first.state_id})
    with pytest.raises(DBAPIError),engine.begin() as connection:
        connection.execute(text("DELETE FROM clinical_state_audit_events WHERE patient_id=:id"),{"id":first.pseudonymous_patient_id})
