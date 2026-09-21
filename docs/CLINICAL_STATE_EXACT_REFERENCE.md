# Clinical State Exact Reference

## Purpose

`PersistedClinicalStateReference` is the Clinical State owner-issued, metadata-only
trust input for an exact persisted `PatientClinicalState`. It enables a future
read-only viewer to reread one exact version after restart without `latest()`,
temporal lookup, history scan or caller-controlled state/version scalars.

## Issuance and resolution

`reference_for(state)` first proves equality with the canonical PostgreSQL payload
and relational metadata under the active tenant context. Later versions require an
already persisted owner-issued predecessor reference. `get_exact(reference)` checks
the persisted reference row, tenant, policy, subject, exact version, predecessor,
provenance digest, canonical state hash and payload/column consistency.

References never contain clinical payload, direct identity, free text, FHIR data or
documents. Historical Clinical State compatibility APIs remain available but do not
qualify as canonical S003 workspace lineage without owner-issued references.

## Persistence

`clinical_state_persisted_references` is tenant-scoped, RLS-protected and append-
only. Runtime reader/writer roles remain `NOBYPASSRLS`; UPDATE, DELETE and TRUNCATE
are unavailable and mutation is rejected by the immutable-history trigger.
