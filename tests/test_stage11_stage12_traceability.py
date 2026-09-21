from dataclasses import FrozenInstanceError,replace
import pytest
from jmoraIs.audit_defense import (AuditDefenseBoundaryRejected,AuditDefenseTraceabilityService,
    InMemoryAuditDefenseEventAdapter,InMemoryAuditDefenseRepository,MedicalDocumentVersionReference,
    PostgreSQLMedicalDocumentTraceAdapter)
from jmoraIs.medical_documents import InMemoryMedicalDocumentRepository,DocumentType
from jmoraIs.tenancy.context import TenantContextBinder
from jmoraIs.tenancy.domain import TenantContext
from tests.test_audit_defense import NOW,setup as defense_setup
from tests.test_medical_document_engine import setup as document_setup
from evaluation.e2e_acceptance.adapters import TraceableAuditDefenseStageAdapter
from evaluation.e2e_acceptance.models import AcceptanceStage,E2ECaseIdentity,ExecutionStatus,StageExecution

def context(tenant="tenant-a"):
    return TenantContext(tenant,"org-a","service","INTERNAL_SERVICE","CLINICAL_VALIDATION","policy","correlation")

def artifacts():
    document=document_setup()[0].generate(document_setup()[3],DocumentType.CLINICAL_REPORT)
    documents=InMemoryMedicalDocumentRepository();documents.append(document)
    defense_service,_,_,reasoning=defense_setup();generated=defense_service.generate(reasoning)
    defenses=InMemoryAuditDefenseRepository();defenses.append(generated)
    audit=InMemoryAuditDefenseEventAdapter()
    return document,documents,generated,defenses,audit

def exact_case():
    from tests.test_audit_defense_reference_states import ExactDocuments
    document,_,generated,defenses,audit=artifacts()
    owner=ExactDocuments(document,context().tenant_id)
    adapter=PostgreSQLMedicalDocumentTraceAdapter(owner)
    service=AuditDefenseTraceabilityService(adapter,defenses,audit,clock=lambda:NOW)
    return document,generated,defenses,owner,service


def test_reference_only_exact_version_link_is_immutable_and_resolvable():
    with TenantContextBinder().bind_tenant(context()):
        document,generated,defenses,owner,service=exact_case()
        linked=service.link_stage11_document(defenses.reference_for_pre_link(generated),owner.reference)
        assert service.resolve_stage11_document(linked)==document
        package=defenses.get_exact(linked)
        reference=package.stage11_document_reference
        assert reference==owner.reference and reference.version==document.version
        assert len(defenses.history(generated.stream_id))==2
        assert package.defense==generated.defense and not hasattr(reference,"sections")
        with pytest.raises(FrozenInstanceError):reference.version=2
        with pytest.raises(AuditDefenseBoundaryRejected):service.link_stage11_document(linked,reference)


def test_exact_version_and_integrity_fail_closed():
    with TenantContextBinder().bind_tenant(context()):
        _,generated,defenses,owner,service=exact_case()
        pre=defenses.reference_for_pre_link(generated)
        with pytest.raises(AuditDefenseBoundaryRejected):service.link_stage11_document(pre,"forged")
        for forged in (replace(owner.reference,version=999),replace(owner.reference,integrity_hash="0"*64)):
            with pytest.raises(AuditDefenseBoundaryRejected):service.link_stage11_document(pre,forged)
        linked=service.link_stage11_document(pre,owner.reference)
        with pytest.raises(AuditDefenseBoundaryRejected):service.resolve_stage11_document(replace(linked,integrity_hash="0"*64))
        package=defenses.get_exact(linked)
        malformed=MedicalDocumentVersionReference("","",0,"","bad","")
        with pytest.raises(AuditDefenseBoundaryRejected):defenses.append(replace(package,package_id="forged",version=3,previous_package_id=package.package_id,stage11_document_reference=malformed))


def test_tenant_mismatch_is_rejected():
    binder=TenantContextBinder()
    with binder.bind_tenant(context()):
        _,generated,defenses,owner,service=exact_case()
        linked=service.link_stage11_document(defenses.reference_for_pre_link(generated),owner.reference)
    with binder.bind_tenant(context("tenant-b")),pytest.raises(AuditDefenseBoundaryRejected):
        service.resolve_stage11_document(linked)

def test_stage12_adapter_manifests_final_linked_package_version_only(monkeypatch):
    from tests.test_audit_defense_reference_states import ExactDocuments
    from evaluation.e2e_acceptance.adapters import E2EAdapterConfigurationError
    from jmoraIs.audit_defense import DefenseReferenceState
    with TenantContextBinder().bind_tenant(context()):
        document,_,generated,defenses,audit=artifacts()
        owner=ExactDocuments(document,context().tenant_id)
        trace_port=PostgreSQLMedicalDocumentTraceAdapter(owner)
        trace=AuditDefenseTraceabilityService(trace_port,defenses,audit,clock=lambda:NOW)
        pre=defenses.reference_for_pre_link(generated)
        def forbidden(*args,**kwargs):raise AssertionError("legacy trust resolution")
        for name in ("history","latest","reference_from_upstream"):monkeypatch.setattr(defenses,name,forbidden)
        monkeypatch.setattr(trace_port,"reference_exact",forbidden)
        adapter=TraceableAuditDefenseStageAdapter(lambda _:pre,defenses,trace_port,trace,document_reference=owner.reference)
        identity=E2ECaseIdentity("execution","case","tenant-a","org-a","service","CLINICAL_VALIDATION","correlation",("policy",),NOW)
        preceding=StageExecution(AcceptanceStage.DOCUMENT,ExecutionStatus.COMPLETED,document.document_stream_id,str(document.version),(document.document.document_id,),NOW)
        value=adapter.execute(identity,preceding);adapter.persist(value);described=adapter.describe(value);adapter.release()
        fresh=TraceableAuditDefenseStageAdapter(forbidden,defenses,trace_port,trace,document_reference=owner.reference)
        reread=fresh.reread_exact(value)
        assert value.state is DefenseReferenceState.STAGE11_LINKED and value.version==2
        assert described.reference_id==value.stream_id and described.version=="2"
        assert reread==value and defenses.get_exact(reread).stage11_document_reference==owner.reference
        with pytest.raises(E2EAdapterConfigurationError):fresh.reread(described.reference_id,described.version)
        with pytest.raises(AuditDefenseBoundaryRejected):fresh.reread_exact(replace(value,reference_id="forged"))
        with pytest.raises(E2EAdapterConfigurationError):adapter.execute(identity,replace(preceding,version="999"))
