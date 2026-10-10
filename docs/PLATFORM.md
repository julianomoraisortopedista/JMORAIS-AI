# Unified platform (local synthetic pilot)

```bash
make local-pilot-up      # builds and starts Postgres, Keycloak, backend and the web platform
```

Open http://localhost/ and sign in (local test users and passwords are in
`~/.local/share/jmorais-local-pilot/.env`; synthetic data only).

Login and password-change pages are in Portuguese and mark the fields `username` /
`current-password`, so Safari/iCloud Keychain can save the login and fill it with Touch ID or
Face ID. **Alterar senha** (top bar) runs the same code+PKCE round trip with
`kc_action=UPDATE_PASSWORD` (policy: at least 12 characters, not the username). After the
physician changes the `medico` password, `.env` no longer holds it, so `make local-pilot-proof`
cannot sign in as the physician until the proof is given another way to authenticate.

Sections after login:

- **Visão geral** — caller context, session counters, guided steps.
- **Pedido médico** — patient documents and history, de-identified before AI, quote-grounded
  fact extraction, physician confirmation, CID/TUSS/OPME and the printable request; see
  `docs/CASE_INTAKE.md`.
- **Modelos de cirurgia** — templates with official TUSS codes, OPME kit, three suppliers
  from the official TUSS 19 table and hospital packages; see `docs/SURGICAL_CATALOG.md`.
  Each template keeps its scientific library ("Montar artigos com o Claude"); see
  `docs/EVIDENCE_LIBRARY.md`.
- **Pacientes** — import the owner-issued launch reference and read the seven exact
  viewers (unchanged S004/S005 behaviour).
- **Evidências / Pergunta em português** — type or dictate the question (or pick a surgery
  template: TUSS procedure + OPME kit); Claude drafts the English claim and PICO terms
  (`jmoraIs/application/question_translation.py`; terms pass the same injection rules; generic
  identifier patterns removed), the fields are filled for review and the PubMed search runs.
  When fewer than 5 records match, the search drops the outcome, then the comparison (counted
  with `esearch` before fetching) and says so.
- **Evidências** — PICO search (PubMed + Crossref, MeSH shown), abstract reading,
  Claude proposals with physician confirm/override/reject, or manual classification
  with a verbatim quote.
- **Documento ao convênio** — coverage facts, STF (ADI 7.265) requirement checklist,
  printable/PDF document with verified Vancouver references and fixed-source legal text.

## External clinical services

OpenEvidence and OrthoEvidence are never queried automatically: their terms restrict
automated/AI access and reuse of content. The Evidências page offers links to open them
with the physician's own login, copies the clinical question, and imports up to 10
PMIDs/DOIs found there (`POST /internal/evidence/api/import`), which are verified in
PubMed/Crossref before joining the same classification flow. Searches accept a recency
window (`since_years`: publications from that year onward, PubMed `[dp]`).

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

## Keeping the local platform reachable

`make local-pilot-up` and `make local-pilot-repair` check that http://127.0.0.1/ answers through
the host port and restart or recreate the frontend when Docker Desktop keeps the port bound but
stops forwarding it. `make local-pilot-watchdog` installs a macOS launch agent
(`com.jmorais.pilot-watchdog`) that runs `deploy/local/watchdog.sh` every 5 minutes: when Docker is
running and the page does not answer, it runs the repair (log:
`~/.local/share/jmorais-local-pilot/watchdog.log`). It never starts Docker by itself.
`make local-pilot-watchdog-off` removes it.
