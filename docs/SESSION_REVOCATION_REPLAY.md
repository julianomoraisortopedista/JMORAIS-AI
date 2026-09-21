# Session Revocation and JTI Replay Protection

Homologation authentication follows the mandatory path:

`Bearer JWT → signature/claims → identity link → principal/tenant → session and JTI gate → purpose → authorization → API`.

A valid JWT signature is necessary but not sufficient. Human identities require a governed session identifier and JTI. Sessions are immutable recognition records; revocation, suspension, principal-wide revocation, expiry and replay detection append security events. Current eligibility is reconstructed from those facts. Reviewer access therefore ends immediately when its session or principal association is no longer valid.

Service principals use a separate `REVOCABLE_CREDENTIAL` policy. They do not inherit human-session semantics or reviewer rights, but their credential/session identifier remains administratively revocable. No unrestricted service identity is introduced.

PostgreSQL stores session attribution, SHA-256 session/JTI hashes and metadata-only events. Raw JWTs and raw provider session identifiers are never stored. A unique JTI-hash constraint and atomic `INSERT ... ON CONFLICT` make single-use consumption race-safe. All tables are tenant-scoped with forced RLS and runtime `NOBYPASSRLS` enforcement.

Replay records remain security metadata until their token expiry plus the configured retention window. They are cleanup-eligible after that point under an audited institutional retention procedure; request-time correctness does not depend on a background scheduler. Revocation history remains append-only and is never cleanup-eligible through the application path.

Homologation startup requires durable session, replay and audit repositories, the canonical session service, enabled validation/replay policy, RLS and database constraints. Development/test may use deterministic adapters. Production identity lifecycle, provider logout/back-channel events, distributed incident automation and institutional retention approval remain out of scope.
