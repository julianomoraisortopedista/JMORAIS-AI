from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone

import pytest

from jmoraIs.infrastructure.managed_secrets import (
    EphemeralSecretProvider, InMemoryKeyMetadataRepository, InMemorySecretSecurityAudit,
    ManagedHmacPseudonymizationKeyAdapter, ManagedKeyService, ProviderReadySecretAdapter,
)
from jmoraIs.secrets.domain import *

NOW=datetime(2026,8,10,tzinfo=timezone.utc)


def references(version="v1"):
    key=KeyReference("memory","patient-hmac",version,SecretPurpose.PSEUDONYMIZATION_HMAC)
    secret=SecretReference("memory","patient-hmac",SecretPurpose.PSEUDONYMIZATION_HMAC,version)
    return key,secret


def setup():
    key,secret=references(); audit=InMemorySecretSecurityAudit()
    provider=EphemeralSecretProvider({("patient-hmac","v1"):(secret,b"a"*32)})
    metadata=InMemoryKeyMetadataRepository((ManagedKeyMetadata(key,KeyState.ACTIVE,NOW,NOW,None,None,"policy-v1"),))
    return key,secret,audit,provider,metadata


def test_secret_lookup_is_callback_scoped_and_metadata_is_immutable():
    key,secret,_,provider,_=setup()
    assert provider.use_secret(secret,actor_id="test",consumer=lambda value:len(value))==32
    with pytest.raises(FrozenInstanceError): secret.reference="raw"
    assert "aaaaaaaa" not in repr(secret) and not hasattr(secret,"value")


def test_missing_secret_wrong_purpose_and_provider_unavailable_fail_closed():
    _,secret,_,provider,_=setup()
    with pytest.raises(SecretResolutionRejected): provider.use_secret(replace(secret,reference="missing"),actor_id="x",consumer=len)
    with pytest.raises(SecretPurposeRejected): provider.use_secret(replace(secret,purpose=SecretPurpose.SIGNING_KEY),actor_id="x",consumer=len)
    provider.available=False
    with pytest.raises(SecretResolutionRejected): provider.use_secret(secret,actor_id="x",consumer=len)
    assert not provider.readiness((secret,)).ready


def test_active_rotation_retired_historical_stability_and_revocation():
    key,_,audit,provider,metadata=setup(); adapter=ManagedHmacPseudonymizationKeyAdapter(provider,metadata,audit,clock=lambda:NOW)
    original=adapter.pseudonymize(key,"national-id:123",actor_id="ingestion")
    successor,successor_secret=references("v2")
    provider._values[("patient-hmac","v2")]=(successor_secret,b"b"*32)
    service=ManagedKeyService(metadata,audit,clock=lambda:NOW); service.rotate(key,successor,actor_id="security")
    assert metadata.get(key).state is KeyState.RETIRED and metadata.get(successor).state is KeyState.ACTIVE
    with pytest.raises(KeyOperationRejected): adapter.pseudonymize(key,"national-id:123",actor_id="new-ingestion")
    historical=adapter.pseudonymize(key,"national-id:123",actor_id="historical-verification",historical=True)
    current=adapter.pseudonymize(successor,"national-id:123",actor_id="new-ingestion")
    assert historical.pseudonymous_id==original.pseudonymous_id
    assert current.pseudonymous_id!=original.pseudonymous_id and current.key_version=="v2"
    assert any(x.event_type is SecretSecurityEventType.RETIRED_KEY_USE for x in audit.events)
    service.revoke(successor,actor_id="security")
    with pytest.raises(KeyOperationRejected): adapter.pseudonymize(successor,"new",actor_id="ingestion")


def test_provider_ready_adapter_audits_failure_without_secret_value():
    class Client:
        available=True
        def resolve(self,reference,version,purpose): raise RuntimeError("backend internal details")
    audit=InMemorySecretSecurityAudit(); adapter=ProviderReadySecretAdapter("vault",Client(),audit,clock=lambda:NOW)
    reference=SecretReference("vault","db/credential",SecretPurpose.POSTGRESQL_CREDENTIALS,"7")
    with pytest.raises(SecretResolutionRejected,match="unavailable"): adapter.use_secret(reference,actor_id="api",consumer=len)
    assert audit.events[-1].reference=="db/credential"
    assert "backend internal" not in repr(audit.events) and not hasattr(audit.events[-1],"value")


def test_pseudonymization_readiness_requires_active_key_and_secret():
    key,_,audit,provider,metadata=setup(); adapter=ManagedHmacPseudonymizationKeyAdapter(provider,metadata,audit)
    assert adapter.readiness(key).ready
    metadata.save(replace(metadata.get(key),state=KeyState.REVOKED,revoked_at=NOW))
    assert not adapter.readiness(key).ready
