import os
from dataclasses import replace
from uuid import uuid4
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine,text
from sqlalchemy.exc import DBAPIError
from jmoraIs.orthopedic_intelligence import *
from tests.test_orthopedic_intelligence import NOW,engine as service_setup,finding,view
pytestmark=pytest.mark.integration
@pytest.fixture(scope="module")
def engine():
    url=os.getenv("JMORAIS_TEST_POSTGRES_URL")
    if not url:pytest.skip("JMORAIS_TEST_POSTGRES_URL is required")
    config=Config("alembic.ini");config.set_main_option("sqlalchemy.url",url);command.upgrade(config,"head")
    value=create_engine(url,future=True);yield value;value.dispose()
def test_postgresql_restart_reconstruction_audit_and_append_only(engine):
    service,_,_,inp=service_setup(view(finding()));generated=service.generate(inp);suffix=uuid4().hex;subject="pt_"+suffix*2;generated=replace(generated,set_id="ortho_"+suffix*2,subject_reference=subject)
    repo=PostgreSQLOrthopedicAssessmentRepository(engine);audit=PostgreSQLOrthopedicAuditAdapter(engine);repo.append(generated)
    event=OrthopedicAuditEvent("ortho_"+uuid4().hex*2,subject,generated.set_id,OrthopedicAuditType.GENERATION,NOW,"engine","GENERATED",(generated.assessment.assessment_id,),generated.assessment.policy_version);audit.append(event)
    assert PostgreSQLOrthopedicAssessmentRepository(engine).history(subject)==(generated,)
    assert PostgreSQLOrthopedicAuditAdapter(engine).history(subject)==(event,)
    with pytest.raises(DBAPIError),engine.begin() as c:c.execute(text("UPDATE orthopedic_assessment_versions SET review_status='ALTERED' WHERE set_id=:id"),{"id":generated.set_id})
    with pytest.raises(DBAPIError),engine.begin() as c:c.execute(text("DELETE FROM orthopedic_assessment_versions WHERE set_id=:id"),{"id":generated.set_id})
    with pytest.raises(DBAPIError),engine.begin() as c:c.execute(text("DELETE FROM orthopedic_assessment_audit WHERE subject_reference=:id"),{"id":subject})
