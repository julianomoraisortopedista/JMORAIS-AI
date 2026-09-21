# Governed Guideline Source Persistence

`GovernedGuidelineRecord` is the immutable, versioned envelope for guideline inputs consumed by MIP-06. It retains the typed recommendation, source version, appraisal linkage, governance status, provenance, policy, predecessor and creation time without duplicating EvidencePackage payloads.

Canonical path: `Governed appraisal → GovernedGuidelineSourceService → GuidelineRepository → GuidelineQueryPort → GuidelineRecommendationEngine`.

Free text and appraisal-incomplete inputs fail closed. Every change appends a monotonically increasing version with exact predecessor. `current()` returns the latest record, `history()` reconstructs every version, and `applicable()` implements the existing query port in requested-ID order. MIP-06 still evaluates expiry, withdrawal and supersession at use time.

Migration `027_governed_guideline_sources` adds unique guideline/version constraints and a trigger rejecting `UPDATE` and `DELETE`. Reconnection reconstructs the typed source from JSONB and indexed governance metadata.

## Tenancy

Guideline sources are **shared global reference data**. They contain published guideline governance, scientific appraisal references and provenance only. Patient, encounter, case, tenant and customer-organization payloads are prohibited, so the source table has no tenant column or RLS. Tenant-scoped reasoning inputs and recommendation outputs retain their existing RLS boundaries.

## E2E

Stage 9 can resolve governed guideline inputs after restart, execute the unchanged engine, persist the resulting recommendation set, release local state and reread the output through PostgreSQL.
