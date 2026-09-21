# LLM Human Review Security Audit

Stage 14 uses two complementary canonical audit streams. Authentication and pre-tenant failures remain in the existing identity/session/tenant security audits; they are not copied into a tenant-scoped review table before a trusted tenant exists. After canonical tenant resolution, `llm_human_review_security_events` records review attempts, authorization outcomes, integrity/lifecycle/transition rejection and decisions.

The review-security stream is metadata-only, tenant-scoped, RLS-enforced, append-only and hash-linked per correlation ID. It contains opaque identifiers and governance metadata only. Draft content, clinical text, prompts, responses, JWTs, raw JTI, secrets, credentials and direct patient identity are prohibited.

Mandatory audit persistence is fail-closed. `REVIEW_ATTEMPT` and `REVIEW_AUTHORIZED` must be committed before the decision repository is called. The final decision event is persisted after the immutable decision event. A future unit-of-work enhancement may atomically bind these two distinct streams; until then, an unavailable audit backend prevents entry into the decision path, while a failure after decision persistence is surfaced and never silently ignored.

Runtime writer permissions are SELECT/INSERT and reader permissions are SELECT. PostgreSQL triggers reject UPDATE and DELETE. Restart reconstruction validates the security hash chain before returning history.
