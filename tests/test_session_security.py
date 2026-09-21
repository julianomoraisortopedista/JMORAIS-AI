from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from threading import Barrier, Lock, Thread

import pytest

from jmoraIs.api.security import ReadinessCheck
from jmoraIs.identity.domain import PrincipalType
from jmoraIs.identity.session_application import CanonicalSessionSecurityService
from jmoraIs.identity.session_domain import (
    AuthenticatedSession, SessionIdentifier, SessionSecurityPolicy, SessionStatus,
    SessionValidationRejected, SessionValidationRequest,
)

NOW = datetime(2026, 8, 10, tzinfo=timezone.utc)

class MemorySessions:
    def __init__(self): self.values = {}; self.events = []
    def recognize(self, value): self.values.setdefault(value.session_id.value, value); return self.values[value.session_id.value]
    def get(self, value): return self.values.get(value)
    def status(self, session_id, principal_id):
        relevant = [x for x in self.events if x.principal_id == principal_id and x.session_id in (None, session_id)]
        if not relevant: return SessionStatus.ACTIVE
        if relevant[-1].event_type.value.endswith("SUSPENDED"): return SessionStatus.SUSPENDED
        return SessionStatus.REVOKED
    def append_event(self, event): self.events.append(event)
    def readiness(self): return ReadinessCheck("session_repository", True, "AVAILABLE")

class MemoryReplay:
    def __init__(self): self.values = {}; self.lock = Lock()
    def consume(self, *, jti_hash, session, consumed_at, single_use):
        with self.lock:
            old = self.values.get(jti_hash)
            if old is None: self.values[jti_hash] = (session, single_use); return True
            return old[0].session_id == session.session_id and old[0].principal_id == session.principal_id and not old[1] and not single_use
    def readiness(self): return ReadinessCheck("replay_repository", True, "AVAILABLE")

class Audit:
    def __init__(self): self.events = []
    def append(self, event): self.events.append(event)

def session(**changes):
    value = AuthenticatedSession(SessionIdentifier("sid-1"), "principal-1", "tenant-1", "org-1",
        "https://issuer", PrincipalType.HUMAN, NOW - timedelta(minutes=1), NOW + timedelta(minutes=5),
        "session-security-v1", NOW)
    return replace(value, **changes)

def service(*, single_use=False):
    sessions, replay, audit = MemorySessions(), MemoryReplay(), Audit()
    policy = SessionSecurityPolicy(single_use_token_classes=("ACCESS",) if single_use else ("SINGLE_USE",))
    return CanonicalSessionSecurityService(sessions, replay, audit, policy, clock=lambda: NOW), sessions, replay, audit

def request(value=None, *, jti="jti-1", token_class="ACCESS"):
    return SessionValidationRequest(value or session(), jti, token_class, "corr-1")

def test_active_session_and_reusable_jti_are_accepted():
    security, sessions, replay, _ = service()
    security.validate(request()); security.validate(request())
    assert sessions.get("sid-1") == session() and len(replay.values) == 1

@pytest.mark.parametrize("operation,message", [("revoke_session", "revoked"), ("suspend_session", "suspended")])
def test_revoked_and_suspended_sessions_fail_closed(operation, message):
    security, _, _, _ = service()
    security.validate(request())
    getattr(security, operation)("sid-1", "principal-1", "tenant-1", reason="SECURITY", correlation_id="corr")
    with pytest.raises(SessionValidationRejected, match=message): security.validate(request(jti="jti-2"))

def test_expired_session_and_missing_human_jti_fail_closed():
    security, _, _, _ = service()
    with pytest.raises(SessionValidationRejected, match="expired"):
        security.validate(request(session(issued_at=NOW - timedelta(minutes=10), expires_at=NOW - timedelta(minutes=1))))
    with pytest.raises(SessionValidationRejected, match="JTI"):
        security.validate(request(jti=None))

def test_principal_wide_revocation_and_association_mismatch():
    security, sessions, _, _ = service(); security.validate(request())
    security.revoke_principal("principal-1", "tenant-1", reason="DISABLED", correlation_id="corr")
    with pytest.raises(SessionValidationRejected, match="revoked"): security.validate(request(jti="jti-2"))
    other, _, _, _ = service(); other.validate(request())
    with pytest.raises(SessionValidationRejected, match="association"):
        other.validate(request(session(principal_id="forged"), jti="jti-3"))

def test_single_use_jti_replay_and_concurrency_allow_exactly_one():
    security, _, _, audit = service(single_use=True)
    barrier = Barrier(2); outcomes = []
    def run():
        barrier.wait()
        try: security.validate(request()); outcomes.append("OK")
        except SessionValidationRejected: outcomes.append("REPLAY")
    threads = [Thread(target=run) for _ in range(2)]
    for item in threads: item.start()
    for item in threads: item.join()
    assert sorted(outcomes) == ["OK", "REPLAY"]
    assert any(x.event_type.value == "REPLAY_DETECTED" for x in audit.events)

def test_jti_session_principal_and_issuer_associations_are_bound():
    security, _, _, _ = service(); security.validate(request())
    with pytest.raises(SessionValidationRejected, match="replay"):
        security.validate(request(session(session_id=SessionIdentifier("sid-2"))))
    with pytest.raises(SessionValidationRejected, match="association"):
        security.validate(request(session(issuer="https://other")))

def test_service_identity_uses_separate_revocable_policy_without_human_jti():
    security, _, _, _ = service()
    machine = session(principal_type=PrincipalType.SERVICE)
    security.validate(request(machine, jti=None))
    security.revoke_session("sid-1", "principal-1", "tenant-1", reason="CREDENTIAL_REVOKED", correlation_id="corr")
    with pytest.raises(SessionValidationRejected, match="revoked"): security.validate(request(machine, jti=None))

def test_policy_and_models_are_immutable_and_readiness_is_explicit():
    security, _, _, _ = service()
    assert security.readiness().ready
    with pytest.raises(Exception): session().principal_id = "changed"
