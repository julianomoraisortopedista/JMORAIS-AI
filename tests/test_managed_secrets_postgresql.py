from datetime import datetime, timezone
import os
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from jmoraIs.infrastructure.secret_persistence import PostgreSQLKeyMetadataRepository, PostgreSQLSecretSecurityAudit
from jmoraIs.secrets.domain import *

NOW=datetime(2026,8,10,tzinfo=timezone.utc)

def migrated():
    url=os.getenv("JMORAIS_TEST_POSTGRES_URL")
    if not url:pytest.skip("JMORAIS_TEST_POSTGRES_URL is required")
    config=Config("alembic.ini");config.set_main_option("sqlalchemy.url",url);command.upgrade(config,"head")
    return url,create_engine(url,future=True)

@pytest.mark.integration
def test_key_metadata_restart_state_history_and_no_secret_persistence():
    url,engine=migrated(); reference=KeyReference("vault","key-"+uuid4().hex,"1",SecretPurpose.PSEUDONYMIZATION_HMAC)
    repo=PostgreSQLKeyMetadataRepository(engine); active=ManagedKeyMetadata(reference,KeyState.ACTIVE,NOW,NOW,None,None,"policy-v1")
    repo.save(active); repo.save(ManagedKeyMetadata(reference,KeyState.RETIRED,NOW,NOW,NOW,None,"policy-v1"))
    assert PostgreSQLKeyMetadataRepository(create_engine(url,future=True)).get(reference).state is KeyState.RETIRED
    with engine.connect() as connection:
        columns={row[0] for row in connection.execute(text("SELECT column_name FROM information_schema.columns "
            "WHERE table_name IN ('managed_key_metadata','managed_key_state_events')"))}
        states=connection.execute(text("SELECT state FROM managed_key_state_events WHERE key_id=:key ORDER BY sequence_id"),
                                  {"key":reference.key_id}).scalars().all()
    assert states==["ACTIVE","RETIRED"]
    assert not {"secret","secret_value","raw_value","key_material","payload"}.intersection(columns)

@pytest.mark.integration
def test_secret_audit_is_append_only_metadata_only():
    _,engine=migrated(); audit=PostgreSQLSecretSecurityAudit(engine); reference="ref-"+uuid4().hex
    event=SecretSecurityEvent("secret_"+uuid4().hex,SecretSecurityEventType.ROTATION,"vault",reference,"2",
        "security-service",SecretPurpose.SIGNING_KEY,NOW,"policy-v1","ROTATED")
    audit.append(event);assert audit.history(reference)[-1]==event
    with pytest.raises(DBAPIError),engine.begin() as connection:
        connection.execute(text("UPDATE secret_security_events SET outcome='TAMPER' WHERE event_id=:id"),{"id":event.event_id})
    with engine.connect() as connection:
        columns={row[0] for row in connection.execute(text("SELECT column_name FROM information_schema.columns "
            "WHERE table_name='secret_security_events'"))}
    assert not {"value","secret","password","token","payload","key_material"}.intersection(columns)
