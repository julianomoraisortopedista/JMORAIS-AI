# Clinical Workspace — S005

Native ES-module UI. Node >=22 and pnpm are development tools only. Serve static
`dist/` on the same origin as `/internal/api/v1`. No runtime JS framework.

Commands: `pnpm install`, `pnpm test`, `pnpm typecheck`, `pnpm lint`, `pnpm build`.
Then `python3 scripts/runtime-config.py` generates public runtime configuration:

- `JMORAIS_WEB_ENVIRONMENT`: DEVELOPMENT, HOMOLOGATION or PRODUCTION
- `JMORAIS_WEB_OIDC_ISSUER`: exact registered issuer
- `JMORAIS_WEB_OIDC_CLIENT_ID`: registered public client
- `JMORAIS_WEB_OIDC_REDIRECT_URI`: registered same-origin callback
- `JMORAIS_WEB_OIDC_SCOPES`: approved scopes separated by spaces, including openid

No defaults or secrets. Missing config shows unavailable. DEVELOPMENT permits
loopback HTTP; otherwise HTTPS. Provider must support Code + PKCE S256, RS256 ID
tokens and public code exchange (with browser CORS). API independently validates
the access token and IAM. Actual values remain deployment prerequisites.

Serve the callback path with index.html. Configure no-store for HTML/config/API,
no-referrer and CSP limited to self plus configured IdP endpoints. Origin, port and
TLS termination use deployment configuration; no port is selected here.

Access token is memory-only. Single-use PKCE transaction (state/nonce/verifier and
configuration identity) temporarily uses sessionStorage to survive redirect;
expires after five minutes, removed before exchange. No tokens, clinical payloads
or launch references are stored there. Logout clears browser auth state, not the
external IdP session.

After login, import the complete JSON PersistedClinicalWorkspaceLaunchReference
returned by the authorized application producer. This transports the exact
reference, never reconstructs it from IDs. Server checks principal/tenant/org/
purpose and revalidates stored clinical references. No launch creation HTTP route,
patient search or mutation controls. Files and clinical responses stay in memory.

Standards-compliant mocked OIDC responses are test-only. Validation status remains
in PROJECT_STATE.md. Missing evidence is not PASS.
