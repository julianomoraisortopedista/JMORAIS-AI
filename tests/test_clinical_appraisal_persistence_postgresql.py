from datetime import datetime, timezone
import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from jmoraIs.appraisal import (
    ClinicalAppraisalPersistenceService,
    ClinicalAppraisalService,
    GovernedEvidenceService,
    InMemoryGovernedEvidenceRepository,
)
from jmoraIs.infrastructure.appraisal_persistence import PostgreSQLClinicalAppraisalRepository
from tests.test_clinical_appraisal_domain import TODAY, request
from tests.test_clinical_intelligence_foundation import issue_direction, package_port


NOW = datetime(2026, 1, 2, tzinfo=timezone.utc)


def postgresql_engine():
    url = os.getenv("JMORAIS_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("JMORAIS_TEST_POSTGRES_URL is required")
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    engine = create_engine(url, future=True)
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE clinical_appraisal_records RESTART IDENTITY"))
    return engine


def test_postgresql_appraisal_restart_replay_and_governed_integration():
    engine = postgresql_engine()
    packages = package_port()
    package = issue_direction(packages, "supporting", "postgres-appraisal")
    source = request(package_id=package.package_id)
    repository = PostgreSQLClinicalAppraisalRepository(engine)
    workflow = ClinicalAppraisalPersistenceService(
        ClinicalAppraisalService(packages), repository, clock=lambda: NOW,
    )
    first = workflow.assess_and_persist((source,), as_of=TODAY)[0][0]
    second = workflow.assess_and_persist((source,), as_of=TODAY)[0][0]

    restarted = PostgreSQLClinicalAppraisalRepository(create_engine(engine.url, future=True))
    assert restarted.get(first.appraisal_id) == first
    assert restarted.history(source.recommendation_id) == (first, second)
    assert restarted.current(source.recommendation_id) == second

    governed = GovernedEvidenceService(
        packages, InMemoryGovernedEvidenceRepository(), appraisals=restarted,
        clock=lambda: NOW,
    ).issue_persisted(second.appraisal_id)
    assert governed.appraisal_result_id == second.appraisal_id


def test_postgresql_appraisal_history_rejects_update_and_delete():
    engine = postgresql_engine()
    packages = package_port()
    package = issue_direction(packages, "supporting", "postgres-immutable")
    source = request(package_id=package.package_id)
    record = ClinicalAppraisalPersistenceService(
        ClinicalAppraisalService(packages), PostgreSQLClinicalAppraisalRepository(engine),
        clock=lambda: NOW,
    ).assess_and_persist((source,), as_of=TODAY)[0][0]

    with pytest.raises(Exception, match="append-only"):
        with engine.begin() as connection:
            connection.execute(text(
                "UPDATE clinical_appraisal_records SET status='SUPERSEDED' WHERE appraisal_id=:id"
            ), {"id": record.appraisal_id})
    with pytest.raises(Exception, match="append-only"):
        with engine.begin() as connection:
            connection.execute(text(
                "DELETE FROM clinical_appraisal_records WHERE appraisal_id=:id"
            ), {"id": record.appraisal_id})
