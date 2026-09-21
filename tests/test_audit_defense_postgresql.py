import os
from dataclasses import replace
from uuid import uuid4
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine,text
from sqlalchemy.exc import DBAPIError
from jmoraIs.audit_defense import *
from tests.test_audit_defense import NOW,setup
pytestmark=pytest.mark.integration
@pytest.fixture(scope="module")
def engine():
    url=os.getenv("JMORAIS_TEST_POSTGRES_URL")
    if not url:pytest.skip("JMORAIS_TEST_POSTGRES_URL is required")
    config=Config("alembic.ini");config.set_main_option("sqlalchemy.url",url);command.upgrade(config,"head")
    value=create_engine(url,future=True);yield value;value.dispose()
def test_postgresql_restart_reconstruction_audit_and_append_only(engine):
    service,_,_,inp=setup();value=service.generate(inp);suffix=uuid4().hex;stream="def_"+suffix*2;value=replace(value,package_id="def_"+uuid4().hex*2,stream_id=stream)
    repo=PostgreSQLAuditDefenseRepository(engine);audit=PostgreSQLAuditDefenseEventAdapter(engine);repo.append(value)
    event=AuditDefenseEvent("def_"+uuid4().hex*2,stream,value.package_id,AuditDefenseEventType.GENERATION,NOW,"engine","GENERATED",(value.defense.defense_id,),"MIP-09.1");audit.append(event)
    assert PostgreSQLAuditDefenseRepository(engine).history(stream)==(value,)
    assert PostgreSQLAuditDefenseEventAdapter(engine).history(stream)==(event,)
    with pytest.raises(DBAPIError),engine.begin() as c:c.execute(text("UPDATE audit_defense_versions SET status='ALTERED' WHERE package_id=:id"),{"id":value.package_id})
    with pytest.raises(DBAPIError),engine.begin() as c:c.execute(text("DELETE FROM audit_defense_versions WHERE package_id=:id"),{"id":value.package_id})
    with pytest.raises(DBAPIError),engine.begin() as c:c.execute(text("DELETE FROM audit_defense_events WHERE stream_id=:id"),{"id":stream})
