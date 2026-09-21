from __future__ import annotations

from jmoraIs.gateway_input import HMACPersistedGatewayInputAttestor
from jmoraIs.governed_llm_draft import GovernedDraftAttestor
from jmoraIs.secrets.domain import KeyOperationRejected, KeyState, SecretPurpose, SecretReference


class ManagedAttestationFactory:
    """Infrastructure-only bridge; raw key bytes remain callback scoped."""
    def __init__(self, secrets, metadata): self._secrets,self._metadata=secrets,metadata
    def draft_attestor(self,key_reference,*,actor_id):
        return self._build(key_reference,actor_id,GovernedDraftAttestor)
    def gateway_input_attestor(self,key_reference,*,actor_id):
        return self._build(key_reference,actor_id,HMACPersistedGatewayInputAttestor)
    def _build(self,key_reference,actor_id,constructor):
        if key_reference.purpose is not SecretPurpose.SIGNING_KEY:raise KeyOperationRejected("attestation requires SIGNING_KEY purpose")
        metadata=self._metadata.get(key_reference)
        if metadata is None or metadata.state is not KeyState.ACTIVE:raise KeyOperationRejected("active attestation key is required")
        reference=SecretReference(key_reference.provider,key_reference.key_id,key_reference.purpose,key_reference.version)
        return self._secrets.use_secret(reference,actor_id=actor_id,consumer=constructor)

class ManagedPersistedGatewayInputVerifier:
    """Verifies the original attestation using referenced managed key material."""
    def __init__(self,secrets,metadata,*,actor_id="persisted-gateway-input-verifier"):self._secrets,self._metadata,self._actor=secrets,metadata,actor_id
    def verify(self,value):
        if value.attestation_key_reference is None:return False
        key=value.attestation_key_reference;meta=self._metadata.get(key)
        if meta is None or meta.state in {KeyState.REVOKED}:return False
        reference=SecretReference(key.provider,key.key_id,key.purpose,key.version)
        try:return self._secrets.use_secret(reference,actor_id=self._actor,consumer=lambda raw:HMACPersistedGatewayInputAttestor(raw).verify(value))
        except Exception:return False
