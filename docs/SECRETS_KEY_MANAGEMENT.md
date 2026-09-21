# Secrets and Cryptographic Key Management

JMORAIS-AI homologation resolves credentials and cryptographic material only
through the provider-agnostic secrets boundary. Configuration contains opaque
`SecretReference` and `KeyReference` values—provider, reference/key ID, version
and controlled purpose—never secret bytes or database URLs.

`SecretProviderPort` exposes material only to an infrastructure callback for a
controlled operation. Secret bytes are not returned in domain/application DTOs.
`KeyManagementPort`, `SigningKeyPort` and `PseudonymizationKeyPort` define
capabilities without importing cloud/Vault SDKs. Provider-ready adapters accept
externally constructed AWS, Azure, Google or HashiCorp clients; CI uses
ephemeral process-local material.

Homologation rejects ephemeral providers. PostgreSQL credentials are resolved
inside `SecretBackedDatabaseEngine`; refresh replaces the pool and disposes the
old engine. OIDC/provider references, when applicable, participate in mandatory
readiness. No cloud provider or production deployment is enabled here.

## Pseudonymization and rotation

Patient Context no longer accepts raw HMAC bytes. It delegates to a versioned
key port. The canonical `pt_<HMAC-SHA256>` format remains unchanged, so the same
approved historical key version reproduces existing identifiers.

New writes require an `ACTIVE` key. Rotation activates a successor and retires
the predecessor. Retired keys are restricted to explicit historical
verification; `REVOKED` keys fail closed. Identity mappings may record key ID
and version without storing material.

PostgreSQL stores immutable key metadata, append-only state events and
append-only security audit metadata only. Homologation readiness requires the
provider, database/provider references and active pseudonymization key. External
KMS/HSM onboarding, automated schedules, break-glass governance and production
credential lifecycle remain blockers.
