import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine

from jmoraIs.api.security import ReadinessCheck
from jmoraIs.infrastructure.api_readiness import PostgreSQLApiReadinessAdapter


@pytest.mark.integration
def test_api_readiness_reports_postgresql_and_migrations_available():
    url = os.getenv("JMORAIS_TEST_POSTGRES_URL")
    if not url: pytest.skip("JMORAIS_TEST_POSTGRES_URL is required")
    config = Config("alembic.ini"); config.set_main_option("sqlalchemy.url", url); command.upgrade(config, "head")
    report = PostgreSQLApiReadinessAdapter(create_engine(url), critical_checks=(
        ReadinessCheck("critical_dependencies", True, "AVAILABLE"),)).check()
    assert report.ready
    assert {(item.name, item.code) for item in report.checks} == {
        ("postgresql", "AVAILABLE"), ("migrations", "CURRENT"),
        ("critical_dependencies", "AVAILABLE"),
    }


def test_api_readiness_fails_closed_when_postgresql_is_unavailable():
    engine = create_engine("postgresql+psycopg://invalid:invalid@127.0.0.1:1/invalid",
                           connect_args={"connect_timeout": 1})
    report = PostgreSQLApiReadinessAdapter(engine).check()
    assert not report.ready
    assert report.checks[0].code == "UNAVAILABLE" and report.checks[1].code == "UNKNOWN"
