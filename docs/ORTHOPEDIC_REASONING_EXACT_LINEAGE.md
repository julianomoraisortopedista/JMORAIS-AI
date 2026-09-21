# Orthopedic Assessment → Clinical Reasoning Exact Lineage

New canonical orthopedic assessment sets preserve the exact owner-issued
`PersistedClinicalReasoningInputReference` supplied during generation. The
application validates it through the Clinical Reasoning owner `get_exact` port,
and PostgreSQL persists the identical metadata-only reference in the immutable
set payload. Exact reread revalidates the reference and ID/version consistency.

Historical sets remain readable with
`LEGACY_MISSING_CLINICAL_REASONING_INPUT_REFERENCE`; no scalar backfill is
performed.
