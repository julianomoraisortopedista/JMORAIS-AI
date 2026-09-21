from __future__ import annotations

from typing import Callable, Protocol, TypeVar

from .domain import KeyReference, ManagedKeyMetadata, PseudonymizationResult, SecretReference, SecretSecurityEvent

T = TypeVar("T")


class SecretProviderPort(Protocol):
    homologation_safe: bool
    def use_secret(self, reference: SecretReference, *, actor_id: str, consumer: Callable[[bytes], T]) -> T: ...
    def readiness(self, required: tuple[SecretReference, ...]): ...


class KeyManagementPort(Protocol):
    def metadata(self, reference: KeyReference) -> ManagedKeyMetadata | None: ...
    def rotate(self, current: KeyReference, successor: KeyReference, *, actor_id: str) -> ManagedKeyMetadata: ...
    def revoke(self, reference: KeyReference, *, actor_id: str) -> ManagedKeyMetadata: ...


class SigningKeyPort(Protocol):
    def sign(self, reference: KeyReference, payload: bytes, *, actor_id: str) -> bytes: ...
    def verify(self, reference: KeyReference, payload: bytes, signature: bytes, *, actor_id: str) -> bool: ...


class PseudonymizationKeyPort(Protocol):
    def pseudonymize(self, reference: KeyReference, identity_reference: str, *, actor_id: str,
                     historical: bool = False) -> PseudonymizationResult: ...


class SecretSecurityAuditPort(Protocol):
    def append(self, event: SecretSecurityEvent) -> None: ...
    def history(self, reference: str) -> tuple[SecretSecurityEvent, ...]: ...
