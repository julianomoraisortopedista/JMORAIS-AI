from __future__ import annotations

from datetime import datetime, timezone
import os
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from jmoraIs.infrastructure.identity_persistence import PostgreSQLIdentitySecurityAudit
from jmoraIs.smart_fhir.domain import SmartAuthenticationAuditEvent
from jmoraIs.smart_fhir.infrastructure import CanonicalIdentitySecurityAuditAdapter


@pytest.mark.integration
def test_smart_authentication_metadata_is_restart_safe_append_only_and_token_free():
    url = os.getenv("JMORAIS_TEST_POSTGRES_URL")
    if not url: pytest.skip("JMORAIS_TEST_POSTGRES_URL is required")
    config = Config("alembic.ini"); config.set_main_option("sqlalchemy.url", url); command.upgrade(config, "head")
    engine = create_engine(url, future=True)
    audit = CanonicalIdentitySecurityAuditAdapter(PostgreSQLIdentitySecurityAudit(engine))
    correlation = "smart-" + uuid4().hex
    event = SmartAuthenticationAuditEvent(uuid4().hex, "SUCCESS", "SMART_AUTHENTICATED", correlation,
        "https://ehr.example.test", "external-subject", "smart-policy-v1",
        datetime(2026, 9, 1, tzinfo=timezone.utc))
    audit.append(event)
    engine.dispose()

    restarted_engine = create_engine(url, future=True)
    recovered = CanonicalIdentitySecurityAuditAdapter(
        PostgreSQLIdentitySecurityAudit(restarted_engine)).history(correlation)
    assert recovered == (event,)
    with pytest.raises(DBAPIError), restarted_engine.begin() as connection:
        connection.execute(text("UPDATE identity_security_events SET reason_code='TAMPERED' WHERE event_id=:id"),
                           {"id": event.event_id})
    with restarted_engine.connect() as connection:
        columns = {row[0] for row in connection.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_name='identity_security_events'"))}
    assert not {"token", "jwt", "access_token", "refresh_token", "clinical_payload", "patient_id"}.intersection(columns)
    restarted_engine.dispose()
