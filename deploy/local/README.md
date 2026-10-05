# Synthetic local pilot — not for real patients

`make local-pilot-up` builds and starts PostgreSQL16, Keycloak, backend and UI.
`make local-pilot-down` stops this Compose project without deleting named volumes.
Open http://localhost/; the public PKCE client redirects to exactly http://localhost/.
Credentials are generated once in `~/.local/share/jmorais-local-pilot/.env` (0600),
outside Git. Read LOCAL_PHYSICIAN_PASSWORD privately to sign in as `medico`.
Import one of the three `output/patient-*-launch.json` files from that private directory.
Never paste credentials into chat, terminal commands or logs. All cases are fictional.
`make local-pilot-proof` performs real Keycloak code+PKCE authentication and verifies
three launches and seven read-only viewers, readiness, rejection and replay.
HTTP is confined to the loopback-published synthetic stack. No production setting
is changed. The backend does not receive the database-owner password.
Existing owner fixture builders supply synthetic data; mock JWT/runtime factories
are not used. This image is deliberately separate from the frozen production RC.

Cloud SQL verifier compatibility remains untested.
No Cloud SQL resource or permission was changed for this local pilot.
Cloud deployment still requires separate verification of readonly BYPASSRLS authority.
