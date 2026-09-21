from dataclasses import replace

import pytest

from jmoraIs.audit_defense import AuditDefenseBoundaryRejected,PersistedDefensePackageReference
from jmoraIs.tenancy.context import TenantContextBinder
from tests.test_audit_defense_reference_states import context,memory_case


def _issued():
    generated,defenses,pre,documents,trace=memory_case()
    reference=trace.link_stage11_document(pre,documents.reference)
    return generated,defenses.get_exact(reference),defenses,reference


def test_owner_reference_exact_round_trip_and_pre_traceability_rejection():
    with TenantContextBinder().bind_tenant(context()):
        generated,linked,repository,reference=_issued()
        assert repository.get_exact(reference)==linked
        with pytest.raises(AuditDefenseBoundaryRejected,match="Stage-11"):
            repository.reference_for(generated)


def test_fabricated_stale_and_mismatched_references_fail_closed():
    binder=TenantContextBinder()
    with binder.bind_tenant(context()):
        _,_,repository,reference=_issued()
        for forged in (
            PersistedDefensePackageReference("dpr_fabricated",reference.stream_id,reference.version,reference.package_id,reference.tenant_id,reference.policy_version,reference.integrity_hash,reference.issued_at),
            replace(reference,stream_id="forged"),replace(reference,version=999),
            replace(reference,package_id="forged"),replace(reference,policy_version="forged"),
            replace(reference,integrity_hash="0"*64),
        ):
            with pytest.raises(AuditDefenseBoundaryRejected):repository.get_exact(forged)
    with binder.bind_tenant(context("tenant-b")),pytest.raises(AuditDefenseBoundaryRejected,match="tenant"):
        repository.get_exact(reference)
    with pytest.raises(Exception,match="tenant context"):repository.get_exact(reference)


def test_memory_exact_paths_never_call_history_or_latest(monkeypatch):
    import ast
    import inspect
    import textwrap
    from jmoraIs.audit_defense.infrastructure import InMemoryAuditDefenseRepository
    for method in (InMemoryAuditDefenseRepository.reference_for,InMemoryAuditDefenseRepository.get_exact,InMemoryAuditDefenseRepository._exact_package):
        tree=ast.parse(textwrap.dedent(inspect.getsource(method)))
        calls={node.func.attr for node in ast.walk(tree) if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute)}
        assert not calls & {"history","latest"}
    with TenantContextBinder().bind_tenant(context()):
        _,linked,repository,reference=_issued()
        def forbidden(*args):raise AssertionError("historical trust lookup")
        monkeypatch.setattr(repository,"history",forbidden)
        monkeypatch.setattr(repository,"latest",forbidden)
        assert repository.get_exact(reference)==linked
        assert repository.get_exact(repository.reference_for(linked))==linked
        for package in (replace(linked,version=999),replace(linked,package_id="forged"),
                        replace(linked,previous_package_id="forged"),
                        replace(linked,stage11_document_reference=replace(linked.stage11_document_reference,tenant_id="other"))):
            with pytest.raises(AuditDefenseBoundaryRejected):repository.reference_for(package)
    with TenantContextBinder().bind_tenant(context("tenant-b")):
        with pytest.raises(AuditDefenseBoundaryRejected):repository.reference_for(linked)
    with pytest.raises(Exception,match="tenant context"):repository.reference_for(linked)
