"""Approved synthetic owner builder, retaining both owner-issued timeline members."""
from dataclasses import replace
from tests import test_reasoning_input_exact_upstream_lineage_postgresql as source


def seed(owner, writer, tenant, suffix):
    first, state = source.persisted_states(writer, tenant, suffix)
    states = source.PostgreSQLClinicalStateExactReferenceRepository(writer, clock=lambda: source.NOW)
    first_ref = states.reference_for(first)
    state_ref = states.reference_for(state)
    packages, appraisals, lifecycle, governed = source.governed_setup(owner, writer, suffix, tenant)
    evidence = source.PostgreSQLGovernedEvidenceExactReferenceRepository(
        writer, packages, appraisals, lifecycle, clock=lambda: source.NOW)
    evidence_ref = evidence.reference_for(governed)
    terms = source.PostgreSQLTerminologyMappingGovernanceRepository(writer)
    term = replace(source.concept("workspace-" + suffix), version="terms-2026.1")
    mapped = source.MappedClinicalConcept(term.preferred_term, source.CodeSystem.ORTHOPEDIC,
        term.version, source.MappingOutcome.MAPPED, (term,), term.canonical_id,
        source.MappingConfidence.HIGH, False, ("prov:" + suffix,))
    record = source.TerminologyMappingGovernanceService(terms, clock=lambda: source.NOW).persist(
        mapped, source_reference="state:" + suffix, target_concept_id=term.canonical_id,
        mapping_type=source.MappingType.EXACT, review_status=source.MappingReviewStatus.AUTO_MAPPED,
        review_required=False, mapping_method="deterministic", policy_version="ST-02")
    term_ref = terms.reference_for(record)
    legacy_state = source.PatientClinicalStateReference(state.state_id, **source.TRACE,
        patient_context_version=state.patient_context_version, clinical_state_version=state.state_version)
    legacy_evidence = source.GovernedEvidenceReference(governed.governed_evidence_id, **source.TRACE,
        evidence_package_reference_id=governed.evidence_package_id, direction=source.EvidenceDirection.SUPPORTING)
    service = source.ClinicalReasoningInputService(source.PostgreSQLClinicalReasoningInputRepository(writer),
        source.PostgreSQLReasoningInputAuditAdapter(writer), clock=lambda: source.NOW,
        clinical_states=states, governed_evidence=evidence, terminology_governance=terms)
    value = service.build(replace(source.draft(), subject_reference=state.pseudonymous_patient_id,
        patient_clinical_state=legacy_state, terminology_version=term.version,
        evidence=source.EvidenceReferenceSummary(supporting=(legacy_evidence,)),
        evidence_packages=(source.EvidencePackageReference(governed.evidence_package_id, **source.TRACE),),
        clinical_state_reference=state_ref, governed_evidence_references=(evidence_ref,),
        terminology_governance_references=(term_ref,)), actor_id="system", source_reference="workspace-fixture")
    reasoning = source.PostgreSQLClinicalReasoningInputExactReferenceRepository(
        writer, states, evidence, terms, clock=lambda: source.NOW)
    return reasoning.reference_for(value), states.timeline_reference_for((first_ref, state_ref))

