import os
import hashlib
import pytest
from uuid import uuid4
from sqlalchemy import create_engine,text
from sqlalchemy.exc import DBAPIError
from alembic import command
from alembic.config import Config
from jmoraIs.patient_context.persistence import PostgreSQLPatientContextRepository
from jmoraIs.patient_context.persistence import PostgreSQLClinicalAccessAuditRepository
from jmoraIs.patient_context.privacy import ClinicalAccessAuditEvent,ClinicalAuditEventType,PurposeOfUse
from tests.test_patient_context_domain import NOW,PATIENT_ID
from tests.test_patient_context_domain import context,entry

pytestmark=pytest.mark.integration

@pytest.fixture(scope="module")
def engine():
    url=os.getenv("JMORAIS_TEST_POSTGRES_URL")
    if not url: pytest.skip("JMORAIS_TEST_POSTGRES_URL is required")
    config=Config("alembic.ini");config.set_main_option("sqlalchemy.url",url);command.upgrade(config,"head")
    value=create_engine(url,future=True);yield value;value.dispose()

def test_postgresql_append_restart_history_and_immutability(engine):
    repository=PostgreSQLPatientContextRepository(engine);suffix=uuid4().hex
    patient_id="pt_"+hashlib.sha256(suffix.encode()).hexdigest();first=context(f"pg-context-1-{suffix}",patient_id=patient_id)
    repository.append(first);second=context(f"pg-context-2-{suffix}",2,first.context_id,entries=(entry(f"pg-consult-{suffix}"),entry(f"pg-onset-{suffix}")),patient_id=patient_id)
    repository.append(second)
    restarted=PostgreSQLPatientContextRepository(engine)
    assert restarted.latest(first.patient_identity.patient_id)==second
    assert restarted.history(first.patient_identity.patient_id)==(first,second)
    with pytest.raises(DBAPIError),engine.begin() as connection:
        connection.execute(text("UPDATE patient_context_versions SET version=3 WHERE context_id=:id"),{"id":first.context_id})
    with pytest.raises(DBAPIError),engine.begin() as connection:
        connection.execute(text("DELETE FROM patient_context_versions WHERE context_id=:id"),{"id":first.context_id})

def test_postgresql_privacy_audit_survives_restart_and_rejects_mutation(engine):
    suffix=uuid4().hex;repository=PostgreSQLClinicalAccessAuditRepository(engine)
    event=ClinicalAccessAuditEvent(f"audit-{suffix}",ClinicalAuditEventType.CONTEXT_ACCESS,"actor","org",PATIENT_ID,
      PurposeOfUse.CLINICAL_DOCUMENTATION,NOW,"privacy-v1","ALLOWED","AUTHORIZED",("context_id",))
    repository.append(event)
    assert event in PostgreSQLClinicalAccessAuditRepository(engine).history(PATIENT_ID)
    with pytest.raises(DBAPIError),engine.begin() as connection:
        connection.execute(text("UPDATE clinical_data_access_audit SET outcome='ALTERED' WHERE event_id=:id"),{"id":event.event_id})
    with pytest.raises(DBAPIError),engine.begin() as connection:
        connection.execute(text("DELETE FROM clinical_data_access_audit WHERE event_id=:id"),{"id":event.event_id})
