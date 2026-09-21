# SMART on FHIR Security Foundation

## Scope

`jmoraIs.smart_fhir` is the protocol-security boundary for deterministic SMART on
FHIR authentication preparation. It validates configuration, signing keys, JWTs,
PKCE, launch metadata and scope syntax. It does not authorize clinical operations,
contact hospital servers, ingest FHIR resources or construct PatientContext.

## Supported profile

- OAuth 2.0 Authorization Code metadata;
- PKCE `S256` only;
- SMART and OpenID Connect discovery parsing from bounded bytes;
- static JWKS parsing and `kid`/`alg` key selection;
- signed access-token and ID-token validation;
- ID-token nonce validation;
- identity, launch and patient-read SMART scope parsing;
- patient, encounter, practitioner, organization and user launch metadata.

Unsupported capabilities, extensions, write scopes, `alg=none`, cross-authority
discovery endpoints and malformed inputs fail closed.

## Trust boundary

The boundary returns immutable validated metadata. It never returns authorization
for a clinical action. Existing canonical IAM remains responsible for linking an
external subject to an internal principal, tenant, role and policy. The FHIR adapter
and `ClinicalIngestionService` remain separate downstream boundaries.

Raw JWTs, refresh tokens, discovery transport state, launch payloads and PHI are
not persisted. Successful and failed validation produces metadata-only events via
the existing append-only identity-security audit. There is no new clinical table or
second identity authority.

## Operational deferrals

Hospital discovery transport, authorization redirects, token exchange, refresh,
key rotation/cache policy and issuer onboarding remain future integration work.
CDS Hooks, Bulk Data, subscriptions, SMART writes and clinical authorization are
outside Sprint S002.
