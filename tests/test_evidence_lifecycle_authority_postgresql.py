"""Prospective exact history and read-only current authority, in the same owner."""
from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from jmoraIs.appraisal import PostgreSQLGovernedEvidenceExactReferenceRepository
from jmoraIs.appraisal.exact_reference import GovernedEvidenceReferenceRejected
from jmoraIs.clinical.governance_persistence import SQLAlchemyGovernedEvidenceLifecycleRepository
from jmoraIs.clinical.lifecycle_exact import LifecycleAuthorityRejected
from jmoraIs.clinical.review_governance import GovernedEvidenceReevaluationService
from jmoraIs.infrastructure.cryptographic_replay import PostgreSQLCryptographicReplayEngine, ReplayIntegrityStatus
from jmoraIs.infrastructure.tenant_database import create_tenant_runtime_engine
from jmoraIs.infrastructure.database_invariants import DuplicateStreamPosition
from jmoraIs.tenancy.context import TenantContextBinder
from jmoraIs.tenancy.domain import TenantContext
from tests.test_governed_evidence_exact_reference_postgresql import database, setup, NOW, TODAY

pytestmark = pytest.mark.integration


@pytest.fixture
def authority():
    url, owner = database()
    suffix = uuid4().hex
    tenant = TenantContext('life-'+suffix, 'org-'+suffix, 'producer', 'INTERNAL_SERVICE',
                           'CLINICAL_VALIDATION', 'IAM-PILOT', 'corr-'+suffix)
    with owner.begin() as c:
        c.execute(text("""INSERT INTO tenants(tenant_id,organization_id,display_name,status,policy_version,created_at)
            VALUES(:t,:o,'NON-LIVE lifecycle','ACTIVE',:p,:at)"""),
            dict(t=tenant.tenant_id, o=tenant.organization_id, p=tenant.policy_version, at=NOW))
    writer = create_tenant_runtime_engine(url, runtime_role='jmorais_application_writer')
    with TenantContextBinder().bind_tenant(tenant):
        packages, appraisals, lifecycle, evidence = setup(owner, writer, suffix, tenant)
        repository = PostgreSQLGovernedEvidenceExactReferenceRepository(writer, packages, appraisals, lifecycle, clock=lambda:NOW)
        reference = repository.reference_for(evidence)
        yield owner, writer, tenant, packages, appraisals, lifecycle, evidence, repository, reference
    writer.dispose()
    owner.dispose()


def forbidden(*args, **kwargs):
    raise AssertionError('history/latest/at/evaluate cannot enter exact resolution')


def test_exact_history_current_readonly_restart_and_negatives(authority, monkeypatch):
    owner, writer, tenant, packages, appraisals, lifecycle, evidence, repository, reference = authority
    historical = lifecycle.get_current_eligibility(evidence)
    exact = lifecycle.reference_for(historical)
    assert exact.policy_version == 'ST-02' != tenant.policy_version
    for name in ('history', 'latest', 'at', 'evaluate', 'current_status'):
        monkeypatch.setattr(lifecycle, name, forbidden, raising=False)
    assert lifecycle.get_exact(exact) == historical
    assert repository.get_exact(reference) == evidence
    with owner.connect() as c:
        before = c.execute(text('SELECT count(*) FROM governed_evidence_lifecycle_events')).scalar_one()
    for _ in range(2):
        assert lifecycle.get_current_eligibility(evidence).status.value == 'ACTIVE'
    with owner.connect() as c:
        assert before == c.execute(text('SELECT count(*) FROM governed_evidence_lifecycle_events')).scalar_one()
    for change in (dict(event_id='wrong'), dict(status='INVALIDATED'), dict(event_hash='0'*64),
                   dict(policy_version='forged'), dict(tenant_id='other'), dict(stream_position=99)):
        with pytest.raises(LifecycleAuthorityRejected):
            lifecycle.get_exact(replace(exact, **change))
    restarted = SQLAlchemyGovernedEvidenceLifecycleRepository(writer)
    assert restarted.get_exact(exact) == historical
    with TenantContextBinder().bind_tenant(replace(tenant, tenant_id='other')):
        with pytest.raises(LifecycleAuthorityRejected):restarted.get_exact(exact)
        with pytest.raises(LifecycleAuthorityRejected):restarted.get_current_eligibility(evidence)
        with writer.connect() as c:
            assert c.execute(text('SELECT count(*) FROM evidence_lifecycle_current')).scalar_one() == 0
    with writer.connect() as c:
        assert tuple(c.execute(text('SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user')).one()) == (False, False)
    for sql in ('DELETE FROM governed_evidence_lifecycle_events', 'UPDATE evidence_lifecycle_current SET event_hash=event_hash'):
        with pytest.raises(DBAPIError), writer.begin() as c:c.execute(text(sql))


@pytest.mark.parametrize('change', ['revoked', 'withdrawn', 'superseded', 'policy'])
def test_subsequent_ineligibility_preserves_historical_event(authority, change):
    owner, writer, tenant, packages, appraisals, lifecycle, evidence, repository, reference = authority
    historical = lifecycle.reference_for(lifecycle.get_current_eligibility(evidence))
    class RevokedPackages:
        def get(self, identifier):raise ValueError('revoked')
    value = evidence
    if change == 'withdrawn':value = replace(evidence, guideline_withdrawn_at=TODAY.isoformat())
    if change == 'superseded':value = replace(evidence, guideline_superseded_by='replacement')
    service = GovernedEvidenceReevaluationService(RevokedPackages() if change=='revoked' else packages,
        lifecycle, policy_version='changed' if change=='policy' else evidence.policy_version,
        appraisal_version=evidence.appraisal_version, clock=lambda:NOW)
    result = service.evaluate(value, as_of=TODAY)
    assert result.status.value == ('INVALIDATED' if change=='revoked' else 'REVIEW_REQUIRED')
    assert lifecycle.get_exact(historical).status.value == 'ACTIVE'
    with pytest.raises(GovernedEvidenceReferenceRejected):repository.get_exact(reference)


def test_projection_atomicity_missing_authority_and_replay_tamper(authority):
    owner, writer, tenant, packages, appraisals, lifecycle, evidence, repository, reference = authority
    engine = PostgreSQLCryptographicReplayEngine(owner)
    stream = tenant.tenant_id+'|'+evidence.governed_evidence_id
    assert engine.replay_evidence_lifecycle_current(stream).integrity_status is ReplayIntegrityStatus.VALID
    assert engine.replay_governed_evidence_reference(reference.reference_id, tenant_id=tenant.tenant_id).integrity_status is ReplayIntegrityStatus.VALID
    # Privileged isolated tamper transactions are rolled back; no legitimate rows rewritten.
    for sql in ('DELETE FROM evidence_lifecycle_current WHERE governed_evidence_id=:id',
                "UPDATE evidence_lifecycle_current SET event_hash=repeat('0',64) WHERE governed_evidence_id=:id",
                'UPDATE evidence_lifecycle_current SET stream_position=999 WHERE governed_evidence_id=:id'):
        with owner.connect() as c:
            transaction = c.begin()
            c.execute(text(sql), dict(id=evidence.governed_evidence_id))
            # Use this transaction's connection for visibility of deliberate tamper.
            class BoundEngine:
                dialect = owner.dialect
                def connect(self):
                    from contextlib import nullcontext
                    return nullcontext(c)
            assert PostgreSQLCryptographicReplayEngine(BoundEngine()).replay_evidence_lifecycle_current(stream).integrity_status is ReplayIntegrityStatus.TAMPERED
            transaction.rollback()
    # A rejected projection checkpoint must roll back the lifecycle event as well.
    with owner.begin() as c:
        c.execute(text("""INSERT INTO cryptographic_stream_checkpoints
            (stream_namespace,stream_id,stream_position,head_hash,recorded_at)
            VALUES('evidence_lifecycle_current',:id,2,:hash,:at)"""), dict(id=stream, hash='0'*64, at=NOW))
    try:
        with pytest.raises(DuplicateStreamPosition):
            GovernedEvidenceReevaluationService(packages,lifecycle,clock=lambda:NOW).evaluate(evidence,as_of=TODAY)
        with owner.connect() as c:
            assert c.execute(text('SELECT count(*) FROM governed_evidence_lifecycle_events WHERE governed_evidence_id=:id'),dict(id=evidence.governed_evidence_id)).scalar_one() == 1
        with pytest.raises(LifecycleAuthorityRejected):lifecycle.get_current_eligibility(evidence)
        assert engine.replay_evidence_lifecycle_current(stream).integrity_status is ReplayIntegrityStatus.TAMPERED
    finally:
        # Remove only the deliberately forged anchor from this isolated test.
        with owner.begin() as c:
            c.execute(text('SET LOCAL session_replication_role=replica'))
            c.execute(text("""DELETE FROM cryptographic_stream_checkpoints
                WHERE stream_namespace='evidence_lifecycle_current' AND stream_id=:id
                  AND stream_position=2 AND head_hash=:hash"""),dict(id=stream,hash='0'*64))


def test_owner_offline_global_replay_and_missing_legacy_authority(authority):
    from contextlib import nullcontext
    owner, writer, tenant, packages, appraisals, lifecycle, evidence, repository, reference = authority
    assert PostgreSQLCryptographicReplayEngine(owner).replay_all().integrity_status is ReplayIntegrityStatus.VALID
    with owner.connect() as c:
        c.execute(text('SET LOCAL ROLE jmorais_offline_replay_verifier'))
        class BoundEngine:
            dialect = owner.dialect
            def connect(self):return nullcontext(c)
        assert PostgreSQLCryptographicReplayEngine(BoundEngine()).replay_all().integrity_status is ReplayIntegrityStatus.VALID
        assert not c.execute(text("SELECT has_table_privilege(current_user,'evidence_lifecycle_current','INSERT,UPDATE,DELETE,TRUNCATE')")).scalar_one()
    with owner.connect() as c:
        transaction = c.begin()
        c.execute(text('DELETE FROM evidence_lifecycle_current WHERE governed_evidence_id=:id'),dict(id=evidence.governed_evidence_id))
        class BoundEngine:
            dialect = owner.dialect
            def connect(self):return nullcontext(c)
        # Directly exercise the same read-only owner query against missing authority.
        isolated = SQLAlchemyGovernedEvidenceLifecycleRepository.__new__(SQLAlchemyGovernedEvidenceLifecycleRepository)
        isolated._engine = BoundEngine()
        with pytest.raises(LifecycleAuthorityRejected):isolated.get_current_eligibility(evidence)
        assert PostgreSQLCryptographicReplayEngine(BoundEngine()).replay_all().integrity_status is ReplayIntegrityStatus.TAMPERED
        transaction.rollback()


def test_forged_lineage_and_legacy_binding_fail_closed(authority):
    from contextlib import nullcontext
    from jmoraIs.appraisal.exact_reference import reference_integrity, LegacyMissingPersistedGovernedEvidenceReference
    owner, writer, tenant, packages, appraisals, lifecycle, evidence, repository, reference = authority
    for change in (dict(lifecycle_event_id='forged'), dict(lifecycle_integrity_hash='0'*64)):
        forged = replace(reference, **change)
        forged = replace(forged, integrity_hash=reference_integrity(forged))
        with pytest.raises(GovernedEvidenceReferenceRejected):repository.get_exact(forged)
    with owner.connect() as c:
        transaction = c.begin()
        c.execute(text('SET LOCAL session_replication_role=replica'))
        c.execute(text('UPDATE governed_evidence_persisted_references SET lifecycle_reference=NULL WHERE reference_id=:id'),dict(id=reference.reference_id))
        class BoundEngine:
            dialect = owner.dialect
            def connect(self):return nullcontext(c)
        legacy = PostgreSQLGovernedEvidenceExactReferenceRepository(BoundEngine(),packages,appraisals,lifecycle,clock=lambda:NOW)
        with pytest.raises(LegacyMissingPersistedGovernedEvidenceReference, match='LEGACY_MISSING_EXACT_LIFECYCLE_REFERENCE'):
            legacy.get_exact(reference)
        assert c.execute(text('SELECT lifecycle_reference IS NULL FROM governed_evidence_persisted_references WHERE reference_id=:id'),dict(id=reference.reference_id)).scalar_one()
        transaction.rollback()
