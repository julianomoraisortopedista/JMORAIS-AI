"""Concrete test-only bindings for the fourteen canonical E2E stages.

The adapters contain orchestration mechanics only. Each binding is composed with the
owning application service and canonical persistence/query ports by acceptance tests.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .models import AcceptanceStage, E2ECaseIdentity, ExecutionStatus, StageExecution


class E2EAdapterConfigurationError(RuntimeError):
    pass

@dataclass(frozen=True)
class ExactTerminologyGovernanceHandoff:
    """Transports owner-issued Stage-4 references without scalar extraction."""
    references:tuple
    def __post_init__(self):
        from jmoraIs.terminology.domain import PersistedTerminologyMappingGovernanceReference
        if not self.references or any(not isinstance(item,PersistedTerminologyMappingGovernanceReference) for item in self.references):
            raise E2EAdapterConfigurationError("owner-issued terminology governance references are required")
        identifiers=tuple(item.reference_id for item in self.references)
        if identifiers!=tuple(sorted(identifiers)) or len(identifiers)!=len(set(identifiers)):
            raise E2EAdapterConfigurationError("terminology governance handoff must be deterministic and unique")

    def bind(self,draft):
        from dataclasses import replace
        from jmoraIs.reasoning_input.application import ClinicalReasoningInputDraft
        if not isinstance(draft,ClinicalReasoningInputDraft):raise E2EAdapterConfigurationError("canonical reasoning-input draft is required")
        return replace(draft,terminology_governance_references=self.references)


@dataclass(frozen=True)
class CanonicalStageBinding:
    execute_service: Callable[[E2ECaseIdentity, StageExecution | None], object]
    persist_artifact: Callable[[object], None]
    reread_artifact: Callable[[str, str], object | None]
    describe_artifact: Callable[[object], StageExecution]


class CanonicalPersistedStageAdapter:
    """Fail-closed persisted-reference adapter; never owns clinical policy."""

    stage: AcceptanceStage

    def __init__(self, binding: CanonicalStageBinding) -> None:
        if not isinstance(binding, CanonicalStageBinding):
            raise E2EAdapterConfigurationError("canonical stage binding is required")
        self._binding = binding
        self._released = False

    def execute(self, identity: E2ECaseIdentity, preceding: StageExecution | None) -> object:
        self._released = False
        return self._binding.execute_service(identity, preceding)

    def persist(self, artifact: object) -> None:
        self._binding.persist_artifact(artifact)

    def release(self) -> None:
        self._released = True

    def reread(self, reference_id: str, version: str) -> object | None:
        if not self._released:
            raise E2EAdapterConfigurationError("process-local artifact must be released before reread")
        return self._binding.reread_artifact(reference_id, version)

    def describe(self, artifact: object) -> StageExecution:
        described = self._binding.describe_artifact(artifact)
        if described.stage is not self.stage:
            raise E2EAdapterConfigurationError("stage binding returned the wrong canonical stage")
        return described


def _stage_adapter(name: str, stage: AcceptanceStage):
    return type(name, (CanonicalPersistedStageAdapter,), {"stage": stage, "__module__": __name__})


AuthorizedClinicalIngestionAdapter = _stage_adapter("AuthorizedClinicalIngestionAdapter", AcceptanceStage.INGESTION)
PatientContextStageAdapter = _stage_adapter("PatientContextStageAdapter", AcceptanceStage.PATIENT_CONTEXT)
ClinicalStateStageAdapter = _stage_adapter("ClinicalStateStageAdapter", AcceptanceStage.CLINICAL_STATE)
TerminologyResolutionStageAdapter = _stage_adapter("TerminologyResolutionStageAdapter", AcceptanceStage.TERMINOLOGY)
EvidencePackageResolutionStageAdapter = _stage_adapter("EvidencePackageResolutionStageAdapter", AcceptanceStage.EVIDENCE_PACKAGE)
ClinicalAppraisalStageAdapter = _stage_adapter("ClinicalAppraisalStageAdapter", AcceptanceStage.CLINICAL_APPRAISAL)
GovernedEvidenceStageAdapter = _stage_adapter("GovernedEvidenceStageAdapter", AcceptanceStage.GOVERNED_EVIDENCE)
ClinicalReasoningInputStageAdapter = _stage_adapter("ClinicalReasoningInputStageAdapter", AcceptanceStage.REASONING_INPUT)
GuidelineRecommendationStageAdapter = _stage_adapter("GuidelineRecommendationStageAdapter", AcceptanceStage.GUIDELINE)
OrthopedicIntelligenceStageAdapter = _stage_adapter("OrthopedicIntelligenceStageAdapter", AcceptanceStage.ORTHOPEDIC)
MedicalDocumentStageAdapter = _stage_adapter("MedicalDocumentStageAdapter", AcceptanceStage.DOCUMENT)
AuditDefenseStageAdapter = _stage_adapter("AuditDefenseStageAdapter", AcceptanceStage.AUDIT_DEFENSE)
LLMGatewayStageAdapter = _stage_adapter("LLMGatewayStageAdapter", AcceptanceStage.LLM_GATEWAY)
HumanReviewStageAdapter = _stage_adapter("HumanReviewStageAdapter", AcceptanceStage.HUMAN_REVIEW)


CANONICAL_ADAPTER_TYPES = (
    AuthorizedClinicalIngestionAdapter, PatientContextStageAdapter, ClinicalStateStageAdapter,
    TerminologyResolutionStageAdapter, EvidencePackageResolutionStageAdapter,
    ClinicalAppraisalStageAdapter, GovernedEvidenceStageAdapter,
    ClinicalReasoningInputStageAdapter, GuidelineRecommendationStageAdapter,
    OrthopedicIntelligenceStageAdapter, MedicalDocumentStageAdapter, AuditDefenseStageAdapter,
    LLMGatewayStageAdapter, HumanReviewStageAdapter,
)


class AuthorizedIngestionPersistenceAdapter:
    """Stage-1 adapter over the real transaction-owning ingestion service."""
    stage=AcceptanceStage.INGESTION
    def __init__(self,service,query_port,command):
        self._service,self._query,self._command=service,query_port,command;self._receipt=None
    def execute(self,identity,preceding):
        if preceding is not None:raise E2EAdapterConfigurationError("ingestion must be the first stage")
        self._receipt=self._service.ingest(self._command);return self._receipt
    def persist(self,artifact):
        # Persistence is owned atomically by ClinicalIngestionService.  This
        # method verifies the commit and deliberately performs no second write.
        record=self._query.get(artifact.ingestion_record_id)
        if record is None or record.patient_context_id!=artifact.context_id or record.patient_context_version!=artifact.version:
            raise E2EAdapterConfigurationError("canonical ingestion record was not atomically persisted")
    def release(self):self._receipt=None;self._service=None;self._command=None
    def reread(self,reference_id,version):
        value=self._query.get(reference_id)
        return value if value is not None and version=="1" else None
    def describe(self,artifact):
        record=self._query.get(artifact.ingestion_record_id)
        return StageExecution(self.stage,ExecutionStatus.COMPLETED,record.ingestion_record_id,"1",
            (record.provenance_reference,record.patient_context_id),record.issued_at)


class PatientContextRereadStageAdapter:
    """Stage-2 exact reread from the persisted Stage-1 context reference."""
    stage=AcceptanceStage.PATIENT_CONTEXT
    def __init__(self,ingestion_query,context_query):
        self._ingestions,self._contexts=ingestion_query,context_query;self._context=None
    def execute(self,identity,preceding):
        if preceding is None or preceding.stage is not AcceptanceStage.INGESTION:
            raise E2EAdapterConfigurationError("persisted Stage-1 reference is required")
        record=self._ingestions.get(preceding.reference_id)
        if record is None:raise E2EAdapterConfigurationError("persisted ingestion record is unavailable")
        self._context=self._contexts.get(record.patient_context_id)
        if self._context is None or self._context.version!=record.patient_context_version:
            raise E2EAdapterConfigurationError("exact persisted PatientContext version is unavailable")
        return self._context
    def persist(self,artifact):
        persisted=self._contexts.get(artifact.context_id)
        if persisted!=artifact:raise E2EAdapterConfigurationError("Stage 2 must not perform a second write")
    def release(self):self._context=None
    def reread(self,reference_id,version):
        value=self._contexts.get(reference_id)
        return value if value is not None and str(value.version)==version else None
    def describe(self,artifact):
        return StageExecution(self.stage,ExecutionStatus.COMPLETED,artifact.context_id,str(artifact.version),
            (artifact.provenance,artifact.patient_identity.provenance),artifact.effective_at)

class TraceableAuditDefenseStageAdapter:
    """Stage-12 handoff transports owner-issued references, never package payloads."""
    stage=AcceptanceStage.AUDIT_DEFENSE
    def __init__(self,generate_service,defense_repository,document_trace_port,traceability_service,*,document_reference):
        self._generate,self._repository,self._documents,self._trace=generate_service,defense_repository,document_trace_port,traceability_service
        self._document_reference=document_reference
    def execute(self,identity,preceding):
        from jmoraIs.audit_defense.domain import PersistedDefensePackageReference,DefenseReferenceState
        from jmoraIs.medical_documents.exact_reference import PersistedMedicalDocumentVersionReference
        if preceding is None or preceding.stage is not AcceptanceStage.DOCUMENT:
            raise E2EAdapterConfigurationError("persisted Stage-11 manifest entry is required")
        reference=self._document_reference
        if not isinstance(reference,PersistedMedicalDocumentVersionReference):
            raise E2EAdapterConfigurationError("owner-issued Medical Document reference is required")
        self._documents.get_exact(reference)
        if (reference.document_stream_id,str(reference.version),reference.tenant_id)!=(preceding.reference_id,preceding.version,identity.tenant_id):
            raise E2EAdapterConfigurationError("Stage-11 manifest/reference mismatch")
        generated=self._generate(identity)
        if not isinstance(generated,PersistedDefensePackageReference) or generated.state is not DefenseReferenceState.PRE_LINK:
            raise E2EAdapterConfigurationError("owner-issued PRE_LINK reference is required")
        self._repository.get_exact(generated)
        return self._trace.link_stage11_document(generated,reference)
    def persist(self,reference):
        self.reread_exact(reference)
    def release(self):pass
    def reread_exact(self,reference):
        from jmoraIs.audit_defense.domain import PersistedDefensePackageReference,DefenseReferenceState
        if not isinstance(reference,PersistedDefensePackageReference) or reference.state is not DefenseReferenceState.STAGE11_LINKED:
            raise E2EAdapterConfigurationError("owner-issued STAGE11_LINKED reference is required")
        package=self._repository.get_exact(reference)
        self._documents.get_exact(package.stage11_document_reference)
        return reference
    def reread(self,reference_id,version):
        raise E2EAdapterConfigurationError("scalar reread is not eligible; use reread_exact(reference)")
    def describe(self,reference):
        self.reread_exact(reference)
        artifact=self._repository.get_exact(reference)
        document_reference=artifact.stage11_document_reference
        provenance=tuple(sorted(set(artifact.defense.provenance_references)|{document_reference.integrity_hash,document_reference.document_id}))
        return StageExecution(self.stage,ExecutionStatus.COMPLETED,artifact.stream_id,str(artifact.version),provenance,artifact.created_at)


class TypedAuditDefenseGatewayInputAdapter:
    """Stage-13 ingress helper that never accepts or extracts identity scalars."""
    def __init__(self,issuer,persisted_inputs,exact_query=None):self._issuer,self._persisted_inputs,self._exact_query=issuer,persisted_inputs,exact_query
    def issue_and_persist(self,final_package):
        value=self._issuer.issue_from_package(final_package)
        return self._persisted_inputs.persist(value)
    def reread_issue_and_persist(self,persisted_reference):
        if self._exact_query is None:raise E2EAdapterConfigurationError("Audit Defense exact query port is required")
        final_package=self._exact_query.get_exact(persisted_reference)
        value=self._issuer.issue_from_package(final_package)
        return self._persisted_inputs.persist(value)
