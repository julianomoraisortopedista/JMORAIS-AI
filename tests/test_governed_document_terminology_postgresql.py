import os
from dataclasses import replace
from uuid import uuid4
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from jmoraIs.medical_documents import PostgreSQLGovernedDocumentTerminologyAdapter
from jmoraIs.terminology import PostgreSQLTerminologyRepository,TerminologyStatus
from tests.test_terminology import concept

def test_postgresql_restart_reconstructs_exact_document_terminology():
    url=os.getenv("JMORAIS_TEST_POSTGRES_URL")
    if not url:pytest.skip("JMORAIS_TEST_POSTGRES_URL is required")
    config=Config("alembic.ini");config.set_main_option("sqlalchemy.url",url);command.upgrade(config,"head")
    suffix=uuid4().hex;value=replace(concept(),canonical_id=f"document-term-{suffix}",display_name=f"Document term {suffix}",preferred_term=f"document-term-{suffix}",synonyms=(),codes=(replace(concept().codes[0],code=f"ORTHO:{suffix}",display=f"Document term {suffix}"),))
    first=PostgreSQLTerminologyRepository(create_engine(url,future=True));first.append(value.canonical_id,value)
    expected=PostgreSQLGovernedDocumentTerminologyAdapter(first).get(value.canonical_id)
    del first
    restarted=PostgreSQLGovernedDocumentTerminologyAdapter(PostgreSQLTerminologyRepository(create_engine(url,future=True)))
    assert restarted.get(value.canonical_id)==expected
    inactive=replace(value,status=TerminologyStatus.DEPRECATED);PostgreSQLTerminologyRepository(create_engine(url,future=True)).append(value.canonical_id,inactive)
    assert restarted.get(value.canonical_id).review_required
