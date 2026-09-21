from dataclasses import replace
import pytest
from jmoraIs.infrastructure.managed_attestation import ManagedAttestationFactory
from jmoraIs.infrastructure.managed_secrets import EphemeralSecretProvider,InMemoryKeyMetadataRepository
from jmoraIs.secrets.domain import *
from tests.test_managed_secrets import NOW

def setup():
    key=KeyReference("memory","draft-signing","v1",SecretPurpose.SIGNING_KEY);secret=SecretReference("memory","draft-signing",SecretPurpose.SIGNING_KEY,"v1")
    metadata=ManagedKeyMetadata(key,KeyState.ACTIVE,NOW,NOW,None,None,"MIP-10.1")
    provider=EphemeralSecretProvider({("draft-signing","v1"):(secret,b"managed-attestation-key-material-32-bytes")})
    return key,provider,InMemoryKeyMetadataRepository((metadata,))
def test_managed_factory_requires_active_versioned_signing_key_and_callback_scope():
    key,provider,metadata=setup();factory=ManagedAttestationFactory(provider,metadata)
    assert factory.draft_attestor(key,actor_id="stage14") and factory.gateway_input_attestor(key,actor_id="stage14")
    metadata.save(replace(metadata.get(key),state=KeyState.REVOKED,revoked_at=NOW))
    with pytest.raises(KeyOperationRejected):factory.draft_attestor(key,actor_id="stage14")
def test_unavailable_provider_and_wrong_purpose_fail_closed():
    key,provider,metadata=setup();provider.available=False
    with pytest.raises(SecretResolutionRejected):ManagedAttestationFactory(provider,metadata).draft_attestor(key,actor_id="stage14")
    with pytest.raises(KeyOperationRejected):ManagedAttestationFactory(provider,metadata).draft_attestor(replace(key,purpose=SecretPurpose.PSEUDONYMIZATION_HMAC),actor_id="stage14")
