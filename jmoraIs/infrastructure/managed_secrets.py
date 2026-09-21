from __future__ import annotations

import hashlib
import hmac
from dataclasses import replace
from datetime import datetime, timezone
from time import monotonic
from uuid import uuid4

from jmoraIs.api.security import ApiMetric, ReadinessCheck
from jmoraIs.secrets.domain import (
    KeyOperationRejected, KeyReference, KeyState, ManagedKeyMetadata, PseudonymizationResult,
    SecretPurposeRejected, SecretReference, SecretResolutionRejected, SecretSecurityEvent,
    SecretSecurityEventType,
)


class EphemeralSecretProvider:
    """Development/test only. Values remain process-local and are never serialized."""
    homologation_safe = False
    def __init__(self, values: dict[tuple[str, str | None], tuple[SecretReference, bytes]], *, metrics=None):
        self._values, self._metrics, self.available = dict(values), metrics, True
    def use_secret(self, reference, *, actor_id, consumer):
        started = monotonic(); status=200
        try:
            if not self.available: raise SecretResolutionRejected("secret provider is unavailable")
            configured = self._values.get((reference.reference, reference.version))
            if configured is None: raise SecretResolutionRejected("managed secret cannot be resolved")
            registered, value = configured
            if registered.purpose is not reference.purpose: raise SecretPurposeRejected("secret purpose is not authorized")
            return consumer(value)
        except Exception:
            status=503; raise
        finally:
            if self._metrics is not None:
                self._metrics.observe(ApiMetric("/security/secrets/resolve", "SECRET", status,
                    round((monotonic()-started)*1000, 3), datetime.now(timezone.utc), "SECRET_RESOLUTION"))
    def readiness(self, required):
        ready = self.available and all((item.reference, item.version) in self._values for item in required)
        return ReadinessCheck("secrets_provider", ready, "AVAILABLE" if ready else "UNAVAILABLE")


class ProviderReadySecretAdapter:
    """Cloud/Vault-ready adapter; the injected client owns transport and credential exchange."""
    homologation_safe = True
    def __init__(self, provider_id: str, client, audit, *, metrics=None, clock=None):
        self.provider_id, self._client, self._audit, self._metrics = provider_id, client, audit, metrics
        self._clock = clock or (lambda: datetime.now(timezone.utc))
    def use_secret(self, reference, *, actor_id, consumer):
        started=monotonic(); outcome="RESOLVED"
        try:
            if reference.provider != self.provider_id:
                outcome="UNAUTHORIZED_PURPOSE"; raise SecretPurposeRejected("secret provider is not authorized")
            value = self._client.resolve(reference.reference, reference.version, reference.purpose.value)
            if not isinstance(value, bytes) or not value: raise SecretResolutionRejected("managed secret cannot be resolved")
            return consumer(value)
        except SecretPurposeRejected:
            self._event(SecretSecurityEventType.UNAUTHORIZED_PURPOSE, reference, actor_id, outcome); raise
        except Exception as exc:
            outcome="FAILED"
            kind = SecretSecurityEventType.PROVIDER_UNAVAILABLE if not getattr(self._client, "available", True) \
                else SecretSecurityEventType.RESOLUTION_FAILURE
            self._event(kind, reference, actor_id, outcome)
            if isinstance(exc, SecretResolutionRejected): raise
            raise SecretResolutionRejected("managed secret provider is unavailable") from exc
        finally:
            if self._metrics is not None:
                status=200 if outcome=="RESOLVED" else 503
                self._metrics.observe(ApiMetric("/security/secrets/resolve", "SECRET", status,
                    round((monotonic()-started)*1000,3), self._clock(), outcome))
    def readiness(self, required):
        try:
            if not getattr(self._client, "available", True): raise SecretResolutionRejected("unavailable")
            for item in required: self.use_secret(item, actor_id="homologation-readiness", consumer=lambda value: len(value)>0)
            return ReadinessCheck("secrets_provider", True, "AVAILABLE")
        except Exception: return ReadinessCheck("secrets_provider", False, "UNAVAILABLE")
    def _event(self, kind, reference, actor, outcome):
        self._audit.append(SecretSecurityEvent("secret_"+uuid4().hex, kind, reference.provider,
            reference.reference, reference.version, actor, reference.purpose, self._clock(), "secrets-policy-v1", outcome))


class AWSSecretsManagerAdapter(ProviderReadySecretAdapter):
    def __init__(self,client,audit,**kwargs): super().__init__("aws-secrets-manager",client,audit,**kwargs)
class AzureKeyVaultAdapter(ProviderReadySecretAdapter):
    def __init__(self,client,audit,**kwargs): super().__init__("azure-key-vault",client,audit,**kwargs)
class GoogleSecretManagerAdapter(ProviderReadySecretAdapter):
    def __init__(self,client,audit,**kwargs): super().__init__("google-secret-manager",client,audit,**kwargs)
class HashiCorpVaultAdapter(ProviderReadySecretAdapter):
    def __init__(self,client,audit,**kwargs): super().__init__("hashicorp-vault",client,audit,**kwargs)


class ManagedKeyService:
    def __init__(self, repository, audit, *, clock=None, metrics=None):
        self._repository,self._audit,self._metrics=repository,audit,metrics; self._clock=clock or (lambda:datetime.now(timezone.utc))
    def metadata(self, reference): return self._repository.get(reference)
    def rotate(self, current, successor, *, actor_id):
        old=self._required(current)
        if old.state not in {KeyState.ACTIVE,KeyState.ROTATING}: raise KeyOperationRejected("only an active key can rotate")
        now=self._clock(); self._repository.save(replace(old,state=KeyState.RETIRED,retired_at=now))
        value=ManagedKeyMetadata(successor,KeyState.ACTIVE,now,now,None,None,old.policy_version); self._repository.save(value)
        self._event(SecretSecurityEventType.ROTATION,successor,actor_id,"ROTATED"); return value
    def revoke(self, reference, *, actor_id):
        value=self._required(reference); now=self._clock(); revoked=replace(value,state=KeyState.REVOKED,revoked_at=now)
        self._repository.save(revoked); self._event(SecretSecurityEventType.REVOCATION,reference,actor_id,"REVOKED"); return revoked
    def _required(self, reference):
        value=self._repository.get(reference)
        if value is None: raise KeyOperationRejected("managed key metadata is unavailable")
        return value
    def _event(self,kind,reference,actor,outcome):
        self._audit.append(SecretSecurityEvent("secret_"+uuid4().hex,kind,reference.provider,reference.key_id,
            reference.version,actor,reference.purpose,self._clock(),"secrets-policy-v1",outcome))
        if self._metrics is not None:
            self._metrics.observe(ApiMetric("/security/keys/lifecycle","KEY",200,0.0,self._clock(),kind.value))


class ManagedHmacPseudonymizationKeyAdapter:
    def __init__(self, secrets, metadata, audit, *, policy_version="secrets-policy-v1", clock=None, metrics=None):
        self._secrets,self._metadata,self._audit,self._metrics=secrets,metadata,audit,metrics; self._policy=policy_version
        self._clock=clock or (lambda:datetime.now(timezone.utc))
    def pseudonymize(self, reference, identity_reference, *, actor_id, historical=False):
        meta=self._metadata.get(reference)
        if meta is None or meta.state is KeyState.REVOKED:
            if self._metrics is not None:self._metrics.observe(ApiMetric("/security/keys/revoked","KEY",403,0.0,self._clock(),"REVOKED_KEY_ATTEMPT"))
            raise KeyOperationRejected("pseudonymization key is unavailable")
        if meta.state is KeyState.RETIRED:
            self._audit.append(SecretSecurityEvent("secret_"+uuid4().hex,SecretSecurityEventType.RETIRED_KEY_USE,
                reference.provider,reference.key_id,reference.version,actor_id,reference.purpose,
                self._clock(),self._policy,"HISTORICAL_ONLY"))
            if not historical: raise KeyOperationRejected("retired key is restricted to historical verification")
        secret_ref=SecretReference(reference.provider,reference.key_id,reference.purpose,reference.version)
        digest=self._secrets.use_secret(secret_ref,actor_id=actor_id,consumer=lambda value:
            hmac.new(value,identity_reference.encode(),hashlib.sha256).hexdigest())
        return PseudonymizationResult("pt_"+digest,reference.key_id,reference.version,self._policy)
    def readiness(self, reference):
        try:
            meta=self._metadata.get(reference)
            if meta is None or meta.state is not KeyState.ACTIVE: raise KeyOperationRejected("no active key")
            self._secrets.use_secret(SecretReference(reference.provider,reference.key_id,reference.purpose,reference.version),
                                     actor_id="homologation-readiness",consumer=lambda value:len(value)>=32)
            return ReadinessCheck("pseudonymization_key",True,"ACTIVE")
        except Exception: return ReadinessCheck("pseudonymization_key",False,"UNAVAILABLE")


class InMemoryKeyMetadataRepository:
    def __init__(self, values=()): self._values={self._key(x.reference):x for x in values}
    def get(self, reference): return self._values.get(self._key(reference))
    def save(self, metadata): self._values[self._key(metadata.reference)]=metadata
    @staticmethod
    def _key(reference): return reference.provider,reference.key_id,reference.version


class InMemorySecretSecurityAudit:
    def __init__(self): self.events=[]
    def append(self,event): self.events.append(event)
    def history(self,reference): return tuple(x for x in self.events if x.reference==reference)
