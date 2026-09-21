# Clinical State Timeline Reference

## Purpose

`PersistedClinicalStateTimelineReference` binds an exact ordered sequence of owner-
issued Clinical State references at a canonical point in time. It is the only
approved input for the future Patient Timeline; repository `history(patient_id)`,
`latest()` and `at()` cannot establish trusted workspace lineage.

## Invariants

- one pseudonymous subject, tenant and policy;
- genesis-first, contiguous positive versions;
- no duplicate or reordered member;
- every predecessor points to the immediately preceding exact reference;
- each member is authentic and independently resolvable through `get_exact()`;
- the collection hash binds ordered member integrity hashes.

`timeline_reference_for()` validates and persists the collection. After restart,
`get_timeline_exact()` reads only its persisted member rows in stored position and
resolves every exact reference. It never scans the Clinical State history to decide
membership.

Timeline and membership tables are metadata-only, tenant-scoped, RLS-protected and
append-only. Issuing a later timeline does not mutate an earlier representation.
