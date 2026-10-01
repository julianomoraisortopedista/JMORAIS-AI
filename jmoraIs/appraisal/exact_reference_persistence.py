from __future__ import annotations
from dataclasses import replace
from datetime import date,datetime,timezone
from uuid import uuid4
from sqlalchemy import text
from jmoraIs.appraisal.application import clinical_appraisal_integrity_hash
from jmoraIs.appraisal.domain import AppraisalRecordStatus,ClinicalAppraisalRecord
from jmoraIs.tenancy.context import current_tenant_context
from .exact_reference import *
from .exact_reference import _hash as canonical_hash
from .governed import GovernedEvidence,governed_evidence_integrity_hash
from .persistence import _decode

class PostgreSQLGovernedEvidenceExactReferenceRepository:
    def __init__(self,engine,packages,appraisals,lifecycle,*,clock=None):
        if engine.dialect.name!="postgresql":raise ValueError("GovernedEvidence exact references require PostgreSQL")
        self._engine,self._packages,self._appraisals,self._lifecycle=engine,packages,appraisals,lifecycle
        self._clock=clock or (lambda:datetime.now(timezone.utc))
    def reference_for(self,evidence):
        if not isinstance(evidence,GovernedEvidence):raise GovernedEvidenceReferenceRejected("typed GovernedEvidence is required")
        tenant=current_tenant_context();row=self._row(evidence.governed_evidence_id)
        if row is None:raise LegacyMissingPersistedGovernedEvidenceReference("LEGACY_MISSING_PERSISTED_GOVERNED_EVIDENCE_REFERENCE")
        canonical=self._canonical(row)
        if canonical!=evidence:raise GovernedEvidenceReferenceRejected("GovernedEvidence does not match canonical persistence")
        appraisal,event=self._validate_upstream(canonical,canonical.policy_version);lifecycle_reference=self._lifecycle.reference_for(event);issued=self._clock()
        unsigned=PersistedGovernedEvidenceReference("ger_"+uuid4().hex,canonical.governed_evidence_id,row["stream_version"],tenant.tenant_id,
            canonical.evidence_package_id,appraisal.appraisal_id,appraisal.appraisal_version,canonical.policy_version,
            event.event_id,event.status.value,event.event_hash,provenance_reference(canonical),canonical.integrity_hash,"0"*64,issued)
        reference=replace(unsigned,integrity_hash=reference_integrity(unsigned))
        with self._engine.begin() as c:c.execute(text("""INSERT INTO governed_evidence_persisted_references
          (reference_id,governed_evidence_id,stream_version,tenant_id,evidence_package_id,appraisal_record_id,
           appraisal_record_version,policy_version,lifecycle_event_id,lifecycle_status,lifecycle_integrity_hash,
           provenance_reference,governed_evidence_integrity_hash,integrity_hash,issued_at,lifecycle_reference)
          VALUES(:reference,:evidence,:version,:tenant,:package,:appraisal,:appraisal_version,:policy,:lifecycle,
           :status,:lifecycle_hash,:provenance,:evidence_hash,:integrity,:issued,CAST(:lifecycle_reference AS jsonb))"""),
          {"reference":reference.reference_id,"evidence":reference.governed_evidence_id,"version":reference.stream_version,
           "tenant":reference.tenant_id,"package":reference.evidence_package_id,"appraisal":reference.appraisal_record_id,
           "appraisal_version":reference.appraisal_record_version,"policy":reference.policy_version,"lifecycle":reference.lifecycle_event_id,
           "status":reference.lifecycle_status,"lifecycle_hash":reference.lifecycle_integrity_hash,"provenance":reference.provenance_reference,
           "evidence_hash":reference.governed_evidence_integrity_hash,"integrity":reference.integrity_hash,"issued":reference.issued_at,"lifecycle_reference":__import__("json").dumps(lifecycle_reference.payload())})
        return reference
    def get_exact(self,reference):
        if not validate_reference_integrity(reference):raise GovernedEvidenceReferenceRejected("authentic owner-issued GovernedEvidence reference is required")
        tenant=current_tenant_context()
        if reference.tenant_id!=tenant.tenant_id:raise GovernedEvidenceReferenceRejected("GovernedEvidence tenant mismatch")
        with self._engine.connect() as c:persisted=c.execute(text("SELECT * FROM governed_evidence_persisted_references WHERE reference_id=:id"),{"id":reference.reference_id}).mappings().first()
        if persisted is None or self._decode_reference(persisted)!=reference:raise GovernedEvidenceReferenceRejected("persisted GovernedEvidence reference is unavailable or inconsistent")
        row=self._row(reference.governed_evidence_id)
        if row is None or row["stream_version"]!=reference.stream_version or row["tenant_id"]!=tenant.tenant_id:raise GovernedEvidenceReferenceRejected("exact GovernedEvidence version is unavailable")
        if persisted["lifecycle_reference"] is None:raise LegacyMissingPersistedGovernedEvidenceReference("LEGACY_MISSING_EXACT_LIFECYCLE_REFERENCE")
        evidence=self._canonical(row);appraisal,event=self._validate_upstream(evidence,reference.policy_version,persisted["lifecycle_reference"])
        actual=(evidence.evidence_package_id,appraisal.appraisal_id,appraisal.appraisal_version,evidence.policy_version,event.event_id,event.status.value,event.event_hash,provenance_reference(evidence),evidence.integrity_hash)
        expected=(reference.evidence_package_id,reference.appraisal_record_id,reference.appraisal_record_version,reference.policy_version,reference.lifecycle_event_id,reference.lifecycle_status,reference.lifecycle_integrity_hash,reference.provenance_reference,reference.governed_evidence_integrity_hash)
        if actual!=expected:raise GovernedEvidenceReferenceRejected("GovernedEvidence reference linkage mismatch")
        return evidence
    def _validate_upstream(self,evidence,policy,lifecycle_reference=None):
        if evidence.integrity_hash!=governed_evidence_integrity_hash(evidence):raise GovernedEvidenceReferenceRejected("GovernedEvidence integrity mismatch")
        if evidence.policy_version!=policy or not evidence.provenance_references:raise GovernedEvidenceReferenceRejected("GovernedEvidence policy or provenance mismatch")
        try:package=self._packages.get(evidence.evidence_package_id)
        except Exception as exc:raise GovernedEvidenceReferenceRejected("EvidencePackage linkage is invalid") from exc
        if package.package_id!=evidence.evidence_package_id:raise GovernedEvidenceReferenceRejected("EvidencePackage linkage mismatch")
        appraisal=self._appraisals.get(evidence.appraisal_result_id)
        if not isinstance(appraisal,ClinicalAppraisalRecord) or appraisal.status is not AppraisalRecordStatus.ELIGIBLE or appraisal.integrity_hash!=clinical_appraisal_integrity_hash(appraisal) or appraisal.evidence_package_id!=evidence.evidence_package_id:raise GovernedEvidenceReferenceRejected("ClinicalAppraisal linkage is invalid")
        # Scientific policy is authenticated by the package/appraisal owner chain,
        # independently of the caller's IAM authorization policy.
        if evidence.policy_version!=package.policy_version or evidence.policy_version!=appraisal.policy_version:raise GovernedEvidenceReferenceRejected("GovernedEvidence owner policy linkage mismatch")
        from jmoraIs.clinical.lifecycle_exact import LifecycleAuthorityRejected
        try:current=self._lifecycle.get_current_eligibility(evidence)
        except LifecycleAuthorityRejected as exc:raise GovernedEvidenceReferenceRejected("GovernedEvidence lifecycle ACTIVE authority rejected") from exc
        if current.status.value!="ACTIVE":raise GovernedEvidenceReferenceRejected("GovernedEvidence lifecycle is not ACTIVE")
        event=current if lifecycle_reference is None else self._lifecycle.resolve_persisted_reference(lifecycle_reference)
        if event.status.value!="ACTIVE" or event.governed_evidence_id!=evidence.governed_evidence_id or event.policy_version!=evidence.policy_version:raise GovernedEvidenceReferenceRejected("historical lifecycle linkage mismatch")
        today=self._clock().date()
        if (evidence.guideline_expiration_date and today>date.fromisoformat(evidence.guideline_expiration_date)) or evidence.guideline_withdrawn_at or evidence.guideline_superseded_by:raise GovernedEvidenceReferenceRejected("GovernedEvidence governance is no longer eligible")
        return appraisal,event
    def _row(self,identifier):
        with self._engine.connect() as c:return c.execute(text("SELECT * FROM governed_evidence_versions WHERE governed_evidence_id=:id"),{"id":identifier}).mappings().first()
    @staticmethod
    def _canonical(row):
        evidence=_decode(row["payload"])
        if (row["governed_evidence_id"],row["evidence_package_id"],row["integrity_hash"],row["issued_at"])!=(evidence.governed_evidence_id,evidence.evidence_package_id,evidence.integrity_hash,evidence.issued_at):raise GovernedEvidenceReferenceRejected("GovernedEvidence relational/payload mismatch")
        return evidence
    @staticmethod
    def _decode_reference(row):return PersistedGovernedEvidenceReference(row["reference_id"],row["governed_evidence_id"],row["stream_version"],row["tenant_id"],row["evidence_package_id"],row["appraisal_record_id"],row["appraisal_record_version"],row["policy_version"],row["lifecycle_event_id"],row["lifecycle_status"],row["lifecycle_integrity_hash"],row["provenance_reference"],row["governed_evidence_integrity_hash"],row["integrity_hash"],row["issued_at"])
