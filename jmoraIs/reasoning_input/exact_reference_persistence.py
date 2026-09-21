from dataclasses import replace
from datetime import datetime,timezone
from uuid import uuid4
from sqlalchemy import text
from jmoraIs.tenancy.context import current_tenant_context
from .domain import ClinicalReasoningInput,ReasoningUpstreamLineageStatus
from .persistence import ReasoningInputJsonCodec
from .exact_reference import *

class PostgreSQLClinicalReasoningInputExactReferenceRepository:
    def __init__(self,engine,clinical_states,governed_evidence,terminology_governance,*,clock=None,codec=None):
        if engine.dialect.name!="postgresql":raise ValueError("exact reasoning references require PostgreSQL")
        self._engine,self._states,self._evidence,self._terms=engine,clinical_states,governed_evidence,terminology_governance
        self._clock=clock or (lambda:datetime.now(timezone.utc));self._codec=codec or ReasoningInputJsonCodec()
    def reference_for(self,value):
        if not isinstance(value,ClinicalReasoningInput) or value.exact_upstream_lineage_status is not ReasoningUpstreamLineageStatus.EXACT:raise LegacyMissingPersistedClinicalReasoningInputReference("LEGACY_MISSING_PERSISTED_CLINICAL_REASONING_INPUT_REFERENCE")
        tenant=current_tenant_context();canonical=self._canonical(value.input_id)
        if canonical!=value:raise ClinicalReasoningInputReferenceRejected("input does not match canonical persistence")
        self._validate(canonical,tenant)
        predecessor=None
        if value.input_version>1:
            with self._engine.connect() as c:predecessor=c.execute(text("SELECT reference_id FROM clinical_reasoning_input_persisted_references WHERE input_id=:id"),{"id":value.previous_input_id}).scalar_one_or_none()
            if not predecessor:raise LegacyMissingPersistedClinicalReasoningInputReference("exact predecessor reference is unavailable")
        issued=self._clock();unsigned=PersistedClinicalReasoningInputReference("rir_"+uuid4().hex,value.input_id,value.input_version,value.previous_input_id,predecessor,value.subject_reference,tenant.tenant_id,tenant.policy_version,provenance_reference(value),input_integrity(self._codec,value),value.clinical_state_reference,value.governed_evidence_references,value.terminology_governance_references,"0"*64,issued)
        reference=replace(unsigned,integrity_hash=reference_integrity(unsigned));payload=self._codec.encode((reference.clinical_state_reference,reference.governed_evidence_references,reference.terminology_governance_references))
        import json
        with self._engine.begin() as c:c.execute(text("""INSERT INTO clinical_reasoning_input_persisted_references(reference_id,input_id,input_version,previous_input_id,predecessor_reference_id,subject_reference,tenant_id,policy_version,provenance_reference,input_integrity_hash,upstream_references,integrity_hash,issued_at) VALUES(:r,:i,:v,:pi,:pr,:s,:t,:p,:prov,:ih,CAST(:u AS jsonb),:h,:at)"""),{"r":reference.reference_id,"i":reference.input_id,"v":reference.input_version,"pi":reference.previous_input_id,"pr":reference.predecessor_reference_id,"s":reference.subject_reference,"t":reference.tenant_id,"p":reference.policy_version,"prov":reference.provenance_reference,"ih":reference.input_integrity_hash,"u":json.dumps(payload,sort_keys=True,separators=(",",":")),"h":reference.integrity_hash,"at":reference.issued_at})
        return reference
    def get_exact(self,reference):
        if not validate_reference_integrity(reference):raise ClinicalReasoningInputReferenceRejected("authentic owner-issued reference is required")
        tenant=current_tenant_context()
        if (reference.tenant_id,reference.policy_version)!=(tenant.tenant_id,tenant.policy_version):raise ClinicalReasoningInputReferenceRejected("tenant or policy mismatch")
        with self._engine.connect() as c:row=c.execute(text("SELECT * FROM clinical_reasoning_input_persisted_references WHERE reference_id=:id"),{"id":reference.reference_id}).mappings().first()
        if row is None or self._decode(row)!=reference:raise ClinicalReasoningInputReferenceRejected("persisted reference is unavailable or inconsistent")
        value=self._canonical(reference.input_id);self._validate(value,tenant)
        if (value.input_version,value.previous_input_id,value.subject_reference,provenance_reference(value),input_integrity(self._codec,value))!=(reference.input_version,reference.previous_input_id,reference.subject_reference,reference.provenance_reference,reference.input_integrity_hash):raise ClinicalReasoningInputReferenceRejected("exact input linkage mismatch")
        return value
    def _canonical(self,identifier):
        with self._engine.connect() as c:row=c.execute(text("SELECT payload FROM clinical_reasoning_input_versions WHERE input_id=:id"),{"id":identifier}).scalar_one_or_none()
        if row is None:raise ClinicalReasoningInputReferenceRejected("exact input is unavailable")
        return self._codec.decode(row)
    def _validate(self,value,tenant):
        if value.clinical_state_reference.tenant_id!=tenant.tenant_id:raise ClinicalReasoningInputReferenceRejected("Clinical State tenant mismatch")
        self._states.get_exact(value.clinical_state_reference)
        for item in value.governed_evidence_references:self._evidence.get_exact(item)
        for item in value.terminology_governance_references:self._terms.get_exact(item)
    def _decode(self,row):
        state,evidence,terms=self._codec.decode(row["upstream_references"])
        return PersistedClinicalReasoningInputReference(row["reference_id"],row["input_id"],row["input_version"],row["previous_input_id"],row["predecessor_reference_id"],row["subject_reference"],row["tenant_id"],row["policy_version"],row["provenance_reference"],row["input_integrity_hash"],state,evidence,terms,row["integrity_hash"],row["issued_at"])
