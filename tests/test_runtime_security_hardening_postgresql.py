import os

import pytest
from sqlalchemy import text

from jmoraIs.infrastructure.tenant_database import create_tenant_runtime_engine


def test_runtime_pool_and_server_timeouts_are_explicit():
    url = os.getenv("JMORAIS_TEST_POSTGRES_URL")
    if not url: pytest.skip("JMORAIS_TEST_POSTGRES_URL is required")
    engine = create_tenant_runtime_engine(url, runtime_role="jmorais_application_writer",
        pool_size=2, max_overflow=0, connect_timeout=3, statement_timeout_ms=4321,
        lock_timeout_ms=1234, idle_transaction_timeout_ms=5678,
        application_name="jmorais-runtime-security-test", require_tls=False)
    try:
        with engine.connect() as connection:
            values = connection.execute(text("""SELECT current_user,
              current_setting('application_name'), current_setting('statement_timeout'),
              current_setting('lock_timeout'), current_setting('idle_in_transaction_session_timeout')""")).one()
            bypass = connection.execute(text(
                "SELECT rolbypassrls FROM pg_roles WHERE rolname=current_user")).scalar_one()
        assert values == ("jmorais_application_writer", "jmorais-runtime-security-test",
                          "4321ms", "1234ms", "5678ms")
        assert not bypass and engine.pool.size() == 2
    finally:
        engine.dispose()
