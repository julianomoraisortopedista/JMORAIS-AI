# Security of the local platform

Check at any time: `make security-check` (read-only; PASS/AVISO/FALHA, never prints secrets).

| Layer | Protection |
|---|---|
| Network | Every port bound to 127.0.0.1 only (80 web, 8081 identity); nothing reachable from the network. Remote access (iPhone) only through a private Tailscale network with HTTPS, never public; two-factor login becomes mandatory when it is enabled. |
| Browser | CSP (`script-src 'self'`, no frames, no plugins, connections only to this origin and the local identity server), X-Frame-Options DENY, nosniff, no referrer, Permissions-Policy (microphone only for this origin), COOP/CORP same-origin, `server_tokens off`, 1 MB request limit. |
| Login | OIDC + PKCE (S256), public client without password grant; lockout after 5 wrong passwords (growing wait up to 15 min), 5-minute access tokens, refresh tokens revoked on use, session idle 30 min / max 10 h, password policy length 12. Applied on every `up`/`repair` and in new realms. |
| Session | The page signs out after 20 minutes without use and clears patient identification from memory; identification is never stored in the browser. |
| AI | Patient identifiers are removed before any model call and the call is blocked if any survives; the Claude key lives only in the macOS Keychain and in the backend process environment. |
| Containers | Application runs as uid 10001 (not root); `no-new-privileges` on every service; all Linux capabilities dropped for the application and identity server. |
| Data at rest | Private state directory 0700 and files 0600 (umask 077); FileVault disk encryption checked; patient data never committed (checked). |
| Availability | Watchdog every 5 minutes repairs the web front. |

Physician actions: keep FileVault on, turn on the macOS firewall (System Settings > Network >
Firewall), keep macOS and Docker Desktop updated, lock the Mac when away.
