# FHIR R4 Mapping Policy

Policy version: `fhir-map-r4-v1`.

## Deterministic mappings

| FHIR resource | Canonical representation |
| --- | --- |
| Patient | pseudonymous PatientIdentity linkage and permitted demographics |
| Practitioner | attributable source/reference resolution only |
| Organization | source-organization reference resolution only |
| Encounter | Encounter |
| Condition | ClinicalProblem |
| Observation | LaboratoryResult |
| Procedure | ProcedureHistory |
| MedicationStatement | Medication |
| AllergyIntolerance | Allergy |
| DiagnosticReport | ClinicalNoteReference plus resolved Observation references |
| DocumentReference | ClinicalNoteReference |
| ImagingStudy | ImagingStudy metadata, with no diagnostic interpretation |
| Coverage | metadata-only ClinicalNoteReference |
| CarePlan | FollowUpPlan |

No absent diagnosis, procedure, medication, allergy, encounter, result, laterality
or certainty is inferred. Unknown modality/class, unsafe text, missing values,
ambiguous/unknown terminology and conflicting same-version resources yield
`REVIEW_REQUIRED` rather than a stronger clinical assertion.

FHIR codings are validated through `FhirTerminologyValidationPort`, implemented by
an adapter over canonical terminology queries. FHIR never creates concepts,
versions or mappings. Free text is bounded and rejected when absent, unsafe or
identifier-shaped; it does not establish terminology truth.

Provenance binds source system, FHIR release, resource type/ID, source version and
timestamp, mapping-policy version, Bundle hash and governed ingestion authorization.
Raw FHIR JSON is not persisted in PatientContext or interoperability metadata.
