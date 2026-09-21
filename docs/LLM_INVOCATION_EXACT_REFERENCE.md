# LLM Invocation Exact Persisted Reference

`PersistedLLMInvocationReference` is the Gateway-owned, metadata-only trust
reference for one immutable `LLMInvocation`. `reference_for(invocation)` issues it
only after exact comparison with the canonical PostgreSQL invocation, invocation
context, PromptVersion and PersistedGatewayInput. `get_exact(reference)` repeats
those checks after restart and never uses request history, correlation history,
`latest()`, or caller-provided scalar identity.

LLMInvocation has no domain version field and this contract does not invent one.
Exact trust is anchored by immutable invocation identity plus the persisted,
integrity-protected owner reference.

The reference stores no prompt, DTO, output, draft content, credentials, token, or
provider payload. Its table is append-only, tenant-scoped, protected by PostgreSQL
RLS and registered in cryptographic replay through an independent completeness
checkpoint. Historical invocations without this owner-issued reference remain
legacy and cannot qualify for the S003 LLM Trace Viewer.
