import io
import json
import logging
from datetime import datetime, timezone

from sqlalchemy import create_engine

from jmoraIs.application.integrity_alerts import IntegrityAlertType, IntegrityMonitoringService
from jmoraIs.clinical.governance_persistence import (
    ClinicalGovernancePersistenceBase,
    PostgreSQLReviewerIdentityRepository,
)
from jmoraIs.clinical.review_governance import ReviewerIdentity, ReviewerRole, ReviewerStatus
from jmoraIs.infrastructure.integrity_alerts import InMemoryIntegrityAlertAdapter
from jmoraIs.structured_logging import JsonLogFormatter, log_event, redact


def test_reviewer_identity_survives_repository_restart_and_status_is_authoritative():
    engine = create_engine("sqlite://")
    ClinicalGovernancePersistenceBase.metadata.create_all(engine)
    created = datetime(2026, 1, 1, tzinfo=timezone.utc)
    active = ReviewerIdentity("reviewer-1", ReviewerRole.SENIOR_REVIEWER,
        organization_id="org-1", tenant_id="tenant-1", created_at=created, updated_at=created)
    PostgreSQLReviewerIdentityRepository(engine).save(active)
    restarted = PostgreSQLReviewerIdentityRepository(engine)
    recovered = restarted.resolve("reviewer-1")
    assert recovered.reviewer_id == active.reviewer_id
    assert recovered.role == active.role
    assert recovered.organization_id == active.organization_id
    assert restarted.may_review(active)
    suspended = ReviewerIdentity("reviewer-1", ReviewerRole.SENIOR_REVIEWER, active=False,
        status=ReviewerStatus.SUSPENDED, organization_id="org-1", tenant_id="tenant-1",
        created_at=created, updated_at=created)
    restarted.save(suspended)
    assert not PostgreSQLReviewerIdentityRepository(engine).may_review(suspended)


def test_integrity_alerts_are_typed_correlated_and_payload_free():
    adapter = InMemoryIntegrityAlertAdapter()
    service = IntegrityMonitoringService(adapter, clock=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc))
    service.tampered_replay("ledger:claim-1", "job-7")
    service.unauthorized_review("reviewer-9", "request-2")
    assert [event.alert_type for event in adapter.alerts] == [
        IntegrityAlertType.TAMPERED_REPLAY, IntegrityAlertType.UNAUTHORIZED_REVIEW]
    assert adapter.alerts[0].correlation_id == "job-7"
    assert adapter.alerts[0].safe_context == {}


def test_structured_logging_redacts_nested_secrets_and_preserves_correlation():
    assert redact({"token": "abc", "nested": {"patient_id": "123"}}) == {
        "token": "[REDACTED]", "nested": {"patient_id": "[REDACTED]"}}
    stream = io.StringIO()
    logger = logging.Logger("st22")
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonLogFormatter())
    logger.addHandler(handler)
    log_event(logger, "integrity_checked", correlation_id="corr-1", job_id="job-1",
              stream_id="claim-1", safe_context={"authorization": "Bearer secret"})
    payload = json.loads(stream.getvalue())
    assert payload["correlation_id"] == "corr-1"
    assert payload["job_id"] == "job-1"
    assert payload["context"]["authorization"] == "[REDACTED]"


def test_release_workflows_pin_python_and_enforce_coverage():
    ci = open(".github/workflows/ci.yml", encoding="utf-8").read()
    benchmark = open(".github/workflows/live-scientific-benchmark.yml", encoding="utf-8").read()
    assert 'python-version: "3.12.13"' in ci
    assert "--cov-fail-under=90" in ci
    assert "schedule:" in benchmark and "run_live_benchmark.py" in benchmark
