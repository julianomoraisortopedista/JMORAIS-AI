from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from jmoraIs.identity.configuration import OIDCProviderConfig
from jmoraIs.secrets.domain import KeyReference, SecretPurpose, SecretReference
from jmoraIs.identity.session_domain import SessionSecurityPolicy


class InternalApiEnvironment(str, Enum):
    DEVELOPMENT = "DEVELOPMENT"
    TEST = "TEST"
    HOMOLOGATION = "HOMOLOGATION"
    PRODUCTION = "PRODUCTION"


@dataclass(frozen=True)
class RuntimeSecurityPolicy:
    max_request_bytes: int = 1_048_576
    concurrency_limit: int = 100
    request_timeout_seconds: int = 30
    keepalive_seconds: int = 5
    shutdown_grace_seconds: int = 30
    trusted_proxy_cidrs: tuple[str, ...] = ()
    allowed_hosts: tuple[str, ...] = ("localhost", "127.0.0.1")
    tls_termination_required: bool = True
    rate_limit_requests: int = 120
    rate_limit_window_seconds: int = 60
    database_pool_size: int = 10
    database_max_overflow: int = 5
    database_connect_timeout_seconds: int = 10
    database_statement_timeout_ms: int = 30_000
    database_lock_timeout_ms: int = 5_000
    database_idle_transaction_timeout_ms: int = 30_000
    database_tls_required: bool = True
    def __post_init__(self):
        if min(self.max_request_bytes, self.concurrency_limit, self.request_timeout_seconds,
               self.keepalive_seconds, self.shutdown_grace_seconds, self.rate_limit_requests,
               self.rate_limit_window_seconds, self.database_pool_size,
               self.database_connect_timeout_seconds, self.database_statement_timeout_ms,
               self.database_lock_timeout_ms, self.database_idle_transaction_timeout_ms) < 1:
            raise ValueError("bounded production runtime policy is required")
        if self.database_max_overflow < 0 or not self.allowed_hosts or "*" in self.allowed_hosts:
            raise ValueError("production host and pool policy must fail closed")


@dataclass(frozen=True)
class BuildMetadata:
    release_id: str
    build_id: str
    source_revision: str
    built_at: str
    def __post_init__(self):
        if not all((self.release_id, self.build_id, self.source_revision, self.built_at)):
            raise ValueError("complete safe build metadata is required")


@dataclass(frozen=True)
class InternalApiConfig:
    environment: InternalApiEnvironment
    bind_host: str
    database_url: str | None
    oidc: OIDCProviderConfig | None = None
    policy_version: str = "api-access-v1"
    max_request_bytes: int = 1_048_576
    runtime_database_role: str | None = None
    database_credential: SecretReference | None = None
    offline_replay_database_credential: SecretReference | None = None
    pseudonymization_key: KeyReference | None = None
    provider_secret_references: tuple[SecretReference, ...] = ()
    session_security: SessionSecurityPolicy = SessionSecurityPolicy()
    runtime_security: RuntimeSecurityPolicy = RuntimeSecurityPolicy()
    build_metadata: BuildMetadata | None = None

    def __post_init__(self):
        if self.environment in {InternalApiEnvironment.HOMOLOGATION, InternalApiEnvironment.PRODUCTION}:
            if self.database_url is not None or self.oidc is None or self.bind_host not in {"127.0.0.1", "localhost"}:
                raise ValueError("homologation requires secret-backed PostgreSQL, external OIDC and loopback binding")
            if not self.runtime_database_role or self.database_credential is None or self.pseudonymization_key is None:
                raise ValueError("homologation requires runtime role and managed secret/key references")
            if not self.session_security.validation_enabled or not self.session_security.replay_protection_enabled:
                raise ValueError("homologation requires session validation and replay protection")
        if self.environment is InternalApiEnvironment.PRODUCTION and self.build_metadata is None:
            raise ValueError("production requires explicit build metadata")
        if self.environment is InternalApiEnvironment.PRODUCTION:
            verifier = self.offline_replay_database_credential
            if (verifier is None or verifier.purpose is not SecretPurpose.OFFLINE_REPLAY_DATABASE_CREDENTIAL
                    or (self.database_credential is not None
                        and (verifier.provider, verifier.reference)
                        == (self.database_credential.provider, self.database_credential.reference))):
                raise ValueError("production requires a distinct offline replay credential")
        if self.max_request_bytes < 1 or not self.policy_version:
            raise ValueError("secure API configuration is required")


def development_config() -> InternalApiConfig:
    return InternalApiConfig(InternalApiEnvironment.DEVELOPMENT, "127.0.0.1", None)


def test_config(database_url: str | None = None) -> InternalApiConfig:
    return InternalApiConfig(InternalApiEnvironment.TEST, "127.0.0.1", database_url)


def homologation_config(database_credential: SecretReference, oidc: OIDCProviderConfig,
                         pseudonymization_key: KeyReference,
                         provider_secret_references: tuple[SecretReference, ...] = ()) -> InternalApiConfig:
    return InternalApiConfig(InternalApiEnvironment.HOMOLOGATION, "127.0.0.1", None, oidc,
        runtime_database_role="jmorais_application_writer",database_credential=database_credential,
        pseudonymization_key=pseudonymization_key,provider_secret_references=provider_secret_references,
        runtime_security=RuntimeSecurityPolicy(database_tls_required=False))


def production_config(database_credential: SecretReference, oidc: OIDCProviderConfig,
                      pseudonymization_key: KeyReference, build_metadata: BuildMetadata, *,
                      offline_replay_database_credential: SecretReference,
                      runtime_security: RuntimeSecurityPolicy = RuntimeSecurityPolicy(),
                      provider_secret_references: tuple[SecretReference, ...] = ()) -> InternalApiConfig:
    return InternalApiConfig(InternalApiEnvironment.PRODUCTION, "127.0.0.1", None, oidc,
        runtime_database_role="jmorais_application_writer", database_credential=database_credential,
        offline_replay_database_credential=offline_replay_database_credential,
        pseudonymization_key=pseudonymization_key, provider_secret_references=provider_secret_references,
        runtime_security=runtime_security, build_metadata=build_metadata)
