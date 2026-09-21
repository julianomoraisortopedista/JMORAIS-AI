# Canonical Scientific Citation Persistence

## Status and ownership

The Scientific Core owns canonical scientific citation history. A citation record is shared global reference data: it contains no patient, case, organization or tenant payload. Tenant-scoped documents may retain only its opaque identifier.

## Canonical record and issuance

`ScientificCitationRecord` is an immutable, integrity-protected version binding one reconciled publication identity to an active `EvidencePackage` and the exact `VancouverReference` produced by `StrictVancouverFormatter`.

The only supported issuance path is:

```text
authoritative retrieval and reconciliation
→ VERIFIED ScientificArticle
→ EvidencePackage issuance
→ StrictVancouverFormatter
→ ScientificCitationService.issue
→ append-only ScientificCitationRepository
```

The service persists only metadata already accepted by the Scientific Core. Missing formatter-required fields continue to be blocked by `StrictVancouverFormatter`; no field is retrieved, inferred or filled during persistence.

## Trust linkage and query behavior

Each version preserves the package ID, publication identity, metadata hash, provenance references, verification references, ledger references, policy version, editorial status, Vancouver citation ID, formatter version and rendered text. Query rereads the persisted record and revalidates the current package through `ScientificEvidencePackagePort`. Revoked, invalidated, superseded, expired, integrity-invalid or linkage-invalid packages fail closed.

The rendered Vancouver text is never recomputed during query. A formatter-version change creates a successor record and preserves the historical output.

## PostgreSQL and restart semantics

`scientific_citation_record_versions` is append-only. PostgreSQL rejects `UPDATE` and `DELETE`; package/version uniqueness and predecessor validation protect the version stream. Restart query requires only the canonical PostgreSQL package catalog, canonical ledger and citation history. It performs no PubMed, Crossref or other connector call.

## Editorial status

Known canonical status is preserved exactly. `CORRECTED` remains visible and versionable. `RETRACTED` is blocked. Expression-of-concern and unknown statuses remain explicit and are not silently promoted.

## Legacy table decision

The existing `citations` table is classified **LEGACY_NON_AUTHORITATIVE / REMOVE_LATER**. It lacks mandatory package, ledger, verification, formatter-version and integrity linkage and is never queried by the canonical repository. No automatic migration is safe without authoritative linkage evidence.

## Stage 11 role

This history provides the prerequisite query:

```text
EvidencePackage ID → current lifecycle-valid ScientificCitationRecord
```

The downstream Medical Document adapter remains a separate task and must project this record without formatting or scientific revalidation duplication.
