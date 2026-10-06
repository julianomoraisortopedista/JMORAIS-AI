# Unified platform (local synthetic pilot)

```bash
make local-pilot-up      # builds and starts Postgres, Keycloak, backend and the web platform
```

Open http://localhost/ and sign in (local test users and passwords are in
`~/.local/share/jmorais-local-pilot/.env`; synthetic data only).

Sections after login:

- **Visão geral** — caller context, session counters, guided steps.
- **Pacientes** — import the owner-issued launch reference and read the seven exact
  viewers (unchanged S004/S005 behaviour).
- **Evidências** — PICO search (PubMed + Crossref, MeSH shown), abstract reading,
  Claude proposals with physician confirm/override/reject, or manual classification
  with a verbatim quote.
- **Documento ao convênio** — coverage facts, STF (ADI 7.265) requirement checklist,
  printable/PDF document with verified Vancouver references and fixed-source legal text.

## Security

The evidence endpoints are mounted in the backend at `/internal/evidence/` (local
composition `deploy/local/runtime.py`) and authenticated by
`jmoraIs/workbench/platform_auth.py` through the existing IAM: OIDC bearer required,
purpose fixed to CLINICAL_REVIEW, caller-supplied tenant/role/organization headers
refused, WORKSPACE_READ authorization, HUMAN CLINICAL_REVIEWER only. Work state is kept
per principal; decisions are signed with the CRM plus the authenticated principal. The
backend's 30 s request budget is preserved: platform searches return the 10 most
relevant results (~15-20 s).

The Claude key is read from the macOS Keychain at `make local-pilot-up` and passed to the
backend container as process environment only (never written to disk). The local image
installs `anthropic==1.11.0` (pinned; not in the production lock). Without a key the
platform runs in manual-classification mode.

The standalone workbench (`make workbench`, http://127.0.0.1:8770/) remains available.

## Fixed during integration

Browser login never worked: `auth.js`/`client.js` stored `fetch` as an instance method,
which browsers reject with "Illegal invocation". Defaults now wrap `fetch`, and a test
forbids the unbound pattern. Verified with a real browser login against Keycloak.
