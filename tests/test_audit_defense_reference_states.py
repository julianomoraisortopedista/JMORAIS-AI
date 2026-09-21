"""Focused lifecycle tests; in-memory Medical Document port is a unit-test double."""
from dataclasses import FrozenInstanceError, replace
from datetime import timedelta
import ast
import inspect
import textwrap

import pytest

from jmoraIs.audit_defense import (
    AuditDefenseBoundaryRejected, AuditDefenseTraceabilityService, AuditDefenseVersionConflict,
    DefenseReferenceState, InMemoryAuditDefenseRepository, InMemoryAuditDefenseEventAdapter,
    PersistedDefensePackageReference, PostgreSQLAuditDefenseRepository,
)
from jmoraIs.medical_documents import DocumentType
from jmoraIs.audit_defense.domain import MedicalDocumentVersionReference
from jmoraIs.audit_defense.document_traceability import PostgreSQLMedicalDocumentTraceAdapter
from jmoraIs.medical_documents.exact_reference import (
    PersistedMedicalDocumentVersionReference, medical_document_reference_integrity,
)
from jmoraIs.tenancy.context import TenantContextBinder
from jmoraIs.tenancy.domain import TenantContext, MissingTenantContext
from tests.test_audit_defense import NOW, setup as defense_setup
from tests.test_medical_document_engine import setup as document_setup


def context(tenant="states-a"):
    return TenantContext(tenant,"org-"+tenant,"service","INTERNAL_SERVICE","CLINICAL_VALIDATION","policy","corr-"+tenant)


def document_value():
    service,_,_,inp=document_setup()
    return service.generate(inp,DocumentType.CLINICAL_REPORT)


class ExactDocuments:
    """Owner port double, never used outside unit tests."""
    def __init__(self,value,tenant):
        self.value=value
        r=PersistedMedicalDocumentVersionReference("mdr_unit",value.document_stream_id,value.document.document_id,
            value.version_id,value.version,value.previous_version_id,tenant,"policy","CLINICAL_REPORT",
            "TRUE","PENDING_REVIEW","a"*64,"provenance","reason",1,"state",1,None,None,"b"*64,"0"*64,NOW)
        self.reference=replace(r,integrity_hash=medical_document_reference_integrity(r))
        self.calls=[]
    def get_exact(self,reference):
        if reference!=self.reference:raise AuditDefenseBoundaryRejected("document exact reference rejected")
        self.calls.append(reference)
        return self.value


def memory_case():
    service,repo,audit,inp=defense_setup()
    value=service.generate(inp)
    pre=repo.reference_for_pre_link(value)
    documents=ExactDocuments(document_value(),pre.tenant_id)
    trace=AuditDefenseTraceabilityService(documents,repo,audit,clock=lambda:NOW+timedelta(seconds=1))
    return value,repo,pre,documents,trace


def test_pre_link_and_linked_exact_rereads_no_historical_trust(monkeypatch):
    with TenantContextBinder().bind_tenant(context()):
        original,repo,pre,documents,trace=memory_case()
        def forbidden(*args):raise AssertionError("historical trust lookup")
        monkeypatch.setattr(repo,"latest",forbidden);monkeypatch.setattr(repo,"history",forbidden)
        assert repo.get_exact(pre)==original
        assert pre.state is DefenseReferenceState.PRE_LINK
        linked=trace.link_stage11_document(pre,documents.reference)
        reread=repo.get_exact(linked)
        assert linked.state is DefenseReferenceState.STAGE11_LINKED
        assert reread.version==original.version+1 and reread.previous_package_id==original.package_id
        assert reread.defense==original.defense
        assert reread.stage11_document_reference==documents.reference
        assert trace.resolve_stage11_document(linked)==documents.value
        assert len(documents.calls)==2
        assert repo.get_exact(pre)==original and original.stage11_document_reference is None
        with pytest.raises(FrozenInstanceError):pre.state=DefenseReferenceState.STAGE11_LINKED
        with pytest.raises(AuditDefenseVersionConflict):trace.link_stage11_document(pre,documents.reference)
        with pytest.raises(AuditDefenseBoundaryRejected):trace.link_stage11_document(linked,documents.reference)
        with pytest.raises(AuditDefenseBoundaryRejected):repo.reference_for_pre_link(reread)
        with pytest.raises(AuditDefenseBoundaryRejected):repo.reference_for(original)
        with pytest.raises(AuditDefenseBoundaryRejected):repo.append(replace(reread,package_id="downgrade",version=reread.version+1,previous_package_id=reread.package_id,stage11_document_reference=None))
        with pytest.raises(AuditDefenseBoundaryRejected):repo.append_linked_reference(pre,replace(original,version=2,previous_package_id=original.package_id))


@pytest.mark.parametrize("changes",[
    {"reference_id":"forged"},{"package_id":"forged"},{"version":999},
    {"policy_version":"forged"},{"integrity_hash":"0"*64},
    {"state":DefenseReferenceState.STAGE11_LINKED},{"state":None},{"state":"PRE_LINK"},
])
def test_forged_pre_link_rejected(changes):
    with TenantContextBinder().bind_tenant(context()):
        _,repo,pre,_,_=memory_case()
        with pytest.raises(AuditDefenseBoundaryRejected):repo.get_exact(replace(pre,**changes))


def test_issuance_requires_exact_persistence_and_tenant():
    binder=TenantContextBinder()
    with binder.bind_tenant(context()):
        value,repo,pre,docs,trace=memory_case()
        for changed in (replace(value,package_id="forged"),replace(value,version=999),replace(value,previous_package_id="forged")):
            with pytest.raises(AuditDefenseBoundaryRejected):repo.reference_for_pre_link(changed)
        for bad in (value.stream_id,value,replace(pre,state=DefenseReferenceState.STAGE11_LINKED)):
            with pytest.raises(AuditDefenseBoundaryRejected):trace.link_stage11_document(bad,docs.reference)
        with pytest.raises(AuditDefenseBoundaryRejected):trace.link_stage11_document(pre,replace(docs.reference,reference_id="forged"))
        linked=trace.link_stage11_document(pre,docs.reference)
    with binder.bind_tenant(context("states-b")):
        for reference in (pre,linked):
            with pytest.raises(AuditDefenseBoundaryRejected):repo.get_exact(reference)
        with pytest.raises(AuditDefenseBoundaryRejected):repo.reference_for_pre_link(value)
    for reference in (pre,linked):
        with pytest.raises(MissingTenantContext):repo.get_exact(reference)


def test_exact_transition_has_no_history_latest_or_scalar_document_resolution():
    methods=(AuditDefenseTraceabilityService.link_stage11_document,AuditDefenseTraceabilityService.resolve_stage11_document,
        PostgreSQLMedicalDocumentTraceAdapter.get_exact,
        InMemoryAuditDefenseRepository.get_exact,InMemoryAuditDefenseRepository._exact_package,
        PostgreSQLAuditDefenseRepository.get_exact,PostgreSQLAuditDefenseRepository._load_exact_package)
    for method in methods:
        tree=ast.parse(textwrap.dedent(inspect.getsource(method)))
        calls={node.func.attr for node in ast.walk(tree) if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute)}
        assert not calls & {"latest","history","at","reference_exact","resolve_exact"}
        assert not any(isinstance(node,ast.Name) and node.id=="MedicalDocumentVersionReference" for node in ast.walk(tree))


def test_stage11_exact_adapter_rejects_legacy_scalars_and_unauthorized_resolution(monkeypatch):
    binder=TenantContextBinder()
    with binder.bind_tenant(context()):
        _,repo,pre,documents,_=memory_case()
        adapter=PostgreSQLMedicalDocumentTraceAdapter(documents)
        def forbidden(*args,**kwargs):raise AssertionError("legacy Stage-11 trust lookup")
        monkeypatch.setattr(adapter,"reference_exact",forbidden)
        monkeypatch.setattr(adapter,"resolve_exact",forbidden)
        trace=AuditDefenseTraceabilityService(adapter,repo,InMemoryAuditDefenseEventAdapter(),clock=lambda:NOW)
        r=documents.reference
        legacy=MedicalDocumentVersionReference(r.document_stream_id,r.document_id,r.version,r.tenant_id,r.integrity_hash,r.policy_version)
        for bad in (legacy,r.document_id,r.version,documents.value):
            with pytest.raises(AuditDefenseBoundaryRejected):trace.link_stage11_document(pre,bad)
            with pytest.raises(AuditDefenseBoundaryRejected):adapter.get_exact(bad)
        assert documents.calls==[]
        linked=trace.link_stage11_document(pre,r)
        assert trace.resolve_stage11_document(linked)==documents.value
        assert documents.calls==[r,r]
        for bad in (pre,linked.stream_id,repo.get_exact(linked)):
            with pytest.raises(AuditDefenseBoundaryRejected):trace.resolve_stage11_document(bad)
    with binder.bind_tenant(context("states-b")):
        with pytest.raises(AuditDefenseBoundaryRejected):trace.resolve_stage11_document(linked)
    with pytest.raises(MissingTenantContext):trace.resolve_stage11_document(linked)
    assert documents.calls==[r,r]
