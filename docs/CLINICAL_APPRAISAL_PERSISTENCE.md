# Canonical Clinical Appraisal Persistence

## Purpose

Clinical Appraisal is persisted as an immutable governance artifact before it can be referenced by newly issued `GovernedEvidence`. This closes the process-local gap between deterministic appraisal and governed clinical consumption.

The canonical flow is:

`EvidencePackage → ClinicalAppraisalService → ClinicalAppraisalRecord → ClinicalAppraisalRepository → GovernedEvidenceService.issue_persisted()`

No raw PubMed result, raw patient context, ORM entity, or anonymous dictionary is accepted by this flow.

## Canonical record

`ClinicalAppraisalRecord` preserves:

- opaque appraisal identifier;
- EvidencePackage and recommendation references;
- framework and framework version;
- monotonically increasing appraisal version and predecessor;
- complete typed appraisal and source request;
- provenance and policy references;
- reviewer attribution/status when present;
- immutable creation timestamp and integrity hash;
- explicit `ELIGIBLE`, `REVIEW_REQUIRED`, or `SUPERSEDED` status.

Every new assessment is appended as a new version. Historical records are never updated or deleted.

## Ports and adapters

The domain/application boundary defines `ClinicalAppraisalRepository` and `ClinicalAppraisalQueryPort`. Development and deterministic tests use the append-only in-memory adapter. Homologation uses `PostgreSQLClinicalAppraisalRepository` and migration `026_clinical_appraisal_history`.

PostgreSQL enforces immutable history with the shared append-only trigger. The repository API deliberately exposes no update or delete operation. Restart reconstruction reads the typed appraisal from the persisted JSONB artifact and its indexed version metadata.

## Tenancy classification

Clinical appraisal history is classified as shared scientific-governance reference data. It is derived from EvidencePackage, published guideline governance and methodological appraisal; it contains no patient, encounter, organization-tenant, or clinical-case payload. It therefore has no `tenant_id` and is not subject to tenant RLS.

Patient- or organization-scoped projections must reference the resulting governed artifact through their existing tenant-aware boundaries. Adding patient or tenant payload to this table is prohibited and requires a separate architectural review.

## GovernedEvidence integration

New compositions must provide the appraisal query port and call `issue_persisted(appraisal_id)`. The service reloads the canonical artifact, rejects missing or non-eligible records, validates provenance, EvidencePackage linkage and framework version, and records the persistent appraisal identifier in `appraisal_result_id`.

The earlier typed `issue(appraisal, request)` entry point remains only for compatibility with existing internal tests and compositions. It does not replace the canonical persisted path and must not be exposed by new adapters.

## Human review

Persistence never promotes `REVIEW_REQUIRED` to approved state. Expired, withdrawn, superseded, or conflicting inputs remain ineligible for governed issuance. Reviewer attribution is preserved when supplied; reviewer decisions continue through canonical reviewer governance.

## Operational limits

- This change does not add an E2E acceptance adapter.
- PostgreSQL availability and migration `026` are mandatory for durable homologation use.
- Keyed signatures and external timestamping are outside this increment; database immutability and deterministic integrity metadata are the current controls.
