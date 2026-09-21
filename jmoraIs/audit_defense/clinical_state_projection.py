from __future__ import annotations

from hashlib import sha256

from jmoraIs.clinical_state.domain import EpistemicStatus, PatientClinicalState

from .domain import AuditDefenseBoundaryRejected, GovernedAuditClinicalFact


class AuditClinicalStateProjectionService:
    """Projects persisted Clinical State references without adding clinical meaning."""

    POLICY = "MIP-09-CLINICAL-FACT-1"

    def project(self, state: PatientClinicalState) -> tuple[GovernedAuditClinicalFact, ...]:
        if not isinstance(state, PatientClinicalState):
            raise AuditDefenseBoundaryRejected("persisted PatientClinicalState is required")
        flags = tuple(sorted(flag.flag_type.value for flag in state.quality_flags))
        review_status = state.review_status.value
        facts: list[GovernedAuditClinicalFact] = []
        for fact_type, items in (
            ("PROBLEM", state.problems), ("SYMPTOM", state.symptoms),
            ("CLINICAL_FINDING", state.findings), ("MEDICATION", state.medications),
            ("ALLERGY", state.allergies), ("PROCEDURE_HISTORY", state.procedures),
            ("IMPLANT", state.implants), ("PAIN", state.pain), ("RISK_FACTOR", state.risk_factors),
        ):
            for item in items:
                facts.append(self._statement(state, item, fact_type, flags, review_status))
        for item in state.laboratory:
            facts.append(self._fact(state, item.reference_id, "LABORATORY_REFERENCE", EpistemicStatus.OBSERVED,
                                    item.provenance, item.collected_at, (), flags, review_status, item.reference_id,
                                    "patient-clinical-state"))
        for item in state.imaging:
            facts.append(self._fact(state, item.reference_id, "IMAGING_REFERENCE", EpistemicStatus.OBSERVED,
                                    item.provenance, item.performed_at, tuple(item.finding_references), flags,
                                    review_status, item.reference_id, item.source))
        for item in state.functional:
            facts.append(self._fact(state, item.reference_id, "FUNCTIONAL_LIMITATION", EpistemicStatus.REPORTED,
                                    item.provenance, item.recorded_at, (), flags, review_status, item.reference_id,
                                    "patient-clinical-state"))
        for item in state.orthopedic:
            facts.append(self._fact(state, item.reference_id, "ORTHOPEDIC_REFERENCE", EpistemicStatus.OBSERVED,
                                    item.provenance, state.as_of, (), flags, review_status, item.reference_id,
                                    "patient-clinical-state"))
        for flag in state.quality_flags:
            reference = self._id(state.state_id, flag.flag_type.value, *flag.references)
            facts.append(self._fact(state, reference, "DATA_QUALITY_REFERENCE", EpistemicStatus.UNKNOWN,
                                    self._quality_provenance(state, flag.references), state.as_of, (), flags,
                                    review_status, reference, "patient-clinical-state-quality"))
        return tuple(facts)

    def _statement(self, state, item, fact_type, flags, review_status):
        terminology = (item.normalized_term,) if item.normalized_term else ()
        return self._fact(state, item.reference_id, fact_type, item.epistemic_status, item.provenance,
                          item.recorded_at, terminology, flags, review_status, item.source_event_id, item.source)

    def _fact(self, state, fact_id, fact_type, epistemic_status, provenance, recorded_at, terminology,
              flags, review_status, source_reference_id, source):
        return GovernedAuditClinicalFact(
            fact_id=fact_id, clinical_state_reference_id=state.state_id,
            clinical_state_version=state.state_version, epistemic_status=epistemic_status.value,
            terminology_concept_ids=tuple(terminology),
            provenance_references=tuple(sorted({provenance, *state.provenance_references})),
            pseudonymous_subject_reference=state.pseudonymous_patient_id, fact_type=fact_type,
            source_reference_id=source_reference_id, source=source, policy_version=self.POLICY,
            recorded_at=recorded_at, quality_flags=flags, review_status=review_status,
        )

    @staticmethod
    def _quality_provenance(state, references):
        return "quality:" + sha256("|".join((state.state_id, *references)).encode()).hexdigest()

    @staticmethod
    def _id(*parts):
        return "audit-fact-" + sha256("|".join(parts).encode()).hexdigest()
