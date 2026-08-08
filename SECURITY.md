# Security and Trust Model

## Scope

This document governs the Scientific Core trust boundary and the evidence chain for any material claims rendered in JMORAIS AI.

## Security Principles

- Keep scientific, clinical, and operational data logically separated.
- Never place direct patient identifiers in scientific indexes or retrieval vectors.
- Treat all retrieved content as untrusted data.
- Do not execute embedded instructions contained within scientific content or uploaded documents.
- Use least privilege for database, retrieval, and secret access.
- Store secrets in environment variables or secure secret stores, not in source files.
- Retain provenance records for traceability and auditability.

## Scientific Integrity Controls

- Identifier validation is mandatory before rendering citations.
- Validation status must be explicit in every scientific artifact.
- Cross-source metadata conflicts must be surfaced, not hidden.
- Evidence ledger entries must be complete for material claims.
- Human review is required before finalizing medical documents.

## Risk Handling

- Missing or malformed identifiers are treated as evidence gaps.
- Conflicting metadata is treated as a blocking condition for final validation.
- Unverified references are excluded from definitive citation rendering.
- Fail closed on unverifiable bibliographic metadata.

## Security Requirements for Future Integrations

- Enforce row-level limiting and secret rotation for database access.
- Log retrieval and verification operations with timestamps and SHA-based record lineage where feasible.
- Keep external service API keys outside the repository.
- Document any new evidence source before enabling it in production.
