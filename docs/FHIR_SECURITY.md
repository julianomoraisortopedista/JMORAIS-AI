# FHIR Security — Sprint S001

FHIR input is authenticated and authorized through the existing tenant, purpose,
legal-basis and clinical-ingestion boundaries. Patient identifiers do not become
canonical identity and are removed by the existing deterministic privacy pipeline.

## Fail-closed controls

- exact FHIR R4 `4.0.1` release;
- bounded byte, resource, nesting, reference-depth, component, result and metadata
  limits;
- UTF-8 JSON and structural resource validation;
- unique logical and fullUrl identities;
- required Patient subject linkage;
- rejection of unresolved, ambiguous, circular and external HTTP(S) references;
- no arbitrary fetches, SSRF, subscriptions, server synchronization or Bulk Data;
- canonical terminology validation for coded concepts;
- exact-reference-only incremental updates;
- tenant-local PostgreSQL RLS and `NOBYPASSRLS` runtime roles;
- metadata-only idempotency projection with no raw FHIR persistence;
- no PHI-bearing logs or observability payloads.

FHIR schema validity does not imply clinical validity. Structural validation,
semantic interoperability validation and canonical governed ingestion remain three
separate gates. Unsafe or clinically ambiguous input cannot silently enter the
canonical context.
