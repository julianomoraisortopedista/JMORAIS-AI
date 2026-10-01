# Remaining external prerequisites — internal pilot

Software release candidate: PASS. LIVE readiness: NOT PROVEN. No new backend
sprint is required by this list. Supply approved metadata through deployment
configuration; never send secret values in chat or commit them.

| Required owner decision/value | Why / where obtained | Configure | Secret? | Validation |
|---|---|---|---|---|
| Approved host, HTTPS origin, listener/routing, allowed hosts | Infrastructure owner; real reachability | Pilot environment and existing runtime policy | No | `make pilot-check`, `make pilot-status`, browser HTTPS |
| Valid certificate/private-key paths and trust chain | Institutional certificate authority | Pilot TLS entries; external owner-only key | Private key yes | `make pilot-check`; verified HTTPS status |
| Production composition factory and managed provider | Deployment owner supplies existing ProductionComposition with approved provider/observers | JMORAIS_PRODUCTION_COMPOSITION_FACTORY; existing production_config | Reference metadata no; resolved material yes | `make pilot-up`; fail-closed startup/readiness |
| PostgreSQL16 endpoint/TLS, runtime and readonly verifier credentials, migration administrator | DBA; least privilege, NOBYPASSRLS runtime, no verifier DML | Existing managed credential references; ephemeral migration credential | Yes | Existing Alembic current/heads must equal 068_offline_medical_dependencies; authenticated status |
| Authorized versioned SIGNING_KEY and separate pseudonymization reference | Existing managed-key owner; retain legitimate historical versions | Existing production_config references | Metadata no; material yes | Production startup and owner exact verification; no legacy backfill |
| Real public OIDC registration | IdP administrator: issuer, client ID, same-origin redirect, scopes, API audience, signed access tokens, role/organization claims | Browser template and existing backend OIDCProviderConfig | Public client metadata no; no browser client secret | Actual login/callback, authorized viewer and negative auth |
| Active tenant/organization, existing authorized administrator, physician subject/role | Institution IAM owner; explicit policy and mappings | Existing IAM bootstrap; then `make pilot-link-physician` | Identity metadata restricted; bearer secret | Authenticated context and denied cross-tenant access |
| Legitimate prospective clinical case and all seven owner-issued references | Approved clinical owners and responsible physician | External LaunchReferences input; `make pilot-create-launch` | Restricted clinical references | Real same-principal bootstrap and seven viewers |
| Durable metadata-only observers, backup/restore owner and retention | Operations/DBA | Existing production observers and DBA procedures | Backend credentials secret | Startup/readiness, audit receipt, isolated restore evidence |

OIDC uses Authorization Code + PKCE S256; require provider support for the current
browser/backend contract. Browser logout clears local authentication; no provider
session-logout integration is claimed. Institutional provider logout enhancements
are POST_RELEASE unless required by that institution's deployment policy.

Separate Git decision: explicit approval is still required before staging/committing
the prepared candidate list. This does not prevent supplying deployment inputs.
Proposed local message: `chore: checkpoint JMORAIS-AI software release candidate`.
No push or merge is authorized.
