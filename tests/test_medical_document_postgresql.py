import os
from dataclasses import replace
from uuid import uuid4
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine,text
from sqlalchemy.exc import DBAPIError
from jmoraIs.medical_documents import *
from tests.test_medical_document_engine import NOW,setup
pytestmark=pytest.mark.integration
@pytest.fixture(scope="module")
def engine():
    url=os.getenv("JMORAIS_TEST_POSTGRES_URL")
    if not url:pytest.skip("JMORAIS_TEST_POSTGRES_URL is required")
    config=Config("alembic.ini");config.set_main_option("sqlalchemy.url",url);command.upgrade(config,"head")
    value=create_engine(url,future=True);yield value;value.dispose()
def test_postgresql_restart_reconstruction_audit_and_append_only(engine):
    service,_,_,inp=setup();value=service.generate(inp,DocumentType.CLINICAL_REPORT);suffix=uuid4().hex;stream="doc_"+suffix*2;value=replace(value,version_id="doc_"+uuid4().hex*2,document_stream_id=stream)
    repo=PostgreSQLMedicalDocumentRepository(engine);audit=PostgreSQLDocumentAuditAdapter(engine);repo.append(value)
    event=DocumentAuditEvent("doc_"+uuid4().hex*2,stream,value.version_id,DocumentAuditType.GENERATION,NOW,"engine","GENERATED",(value.document.document_id,),value.document.policy_versions[-1]);audit.append(event)
    assert PostgreSQLMedicalDocumentRepository(engine).history(stream)==(value,)
    assert PostgreSQLDocumentAuditAdapter(engine).history(stream)==(event,)
    with pytest.raises(DBAPIError),engine.begin() as c:c.execute(text("UPDATE medical_document_versions SET status='ALTERED' WHERE version_id=:id"),{"id":value.version_id})
    with pytest.raises(DBAPIError),engine.begin() as c:c.execute(text("DELETE FROM medical_document_versions WHERE version_id=:id"),{"id":value.version_id})
    with pytest.raises(DBAPIError),engine.begin() as c:c.execute(text("DELETE FROM medical_document_audit WHERE document_stream_id=:id"),{"id":stream})
