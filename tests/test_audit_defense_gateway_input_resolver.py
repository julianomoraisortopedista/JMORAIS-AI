from dataclasses import replace

import pytest

from jmoraIs.audit_defense import (
    AuditDefenseGatewayInputIssuer, AuditDefenseGatewayInputResolver, AuditDefenseBoundaryRejected,
    AuditDefenseTraceabilityService, PostgreSQLMedicalDocumentTraceAdapter,
)
from jmoraIs.gateway_input import HMACPersistedGatewayInputAttestor, PersistedGatewayInputError, persisted_gateway_input_record, persisted_gateway_input_integrity_hash
from jmoraIs.infrastructure.persisted_gateway_input import (
    InMemoryPersistedGatewayInputRepository, PersistedGatewayInputTrustService,
)
from jmoraIs.secrets.domain import KeyReference, SecretPurpose
from jmoraIs.tenancy.context import TenantContextBinder
from tests.test_stage11_stage12_traceability import artifacts, context
from tests.test_audit_defense import NOW
from evaluation.e2e_acceptance.adapters import TypedAuditDefenseGatewayInputAdapter

KEY=b"audit-defense-gateway-input-key-32bytes"
KEY_REF=KeyReference("memory","audit-defense-gateway","v1",SecretPurpose.SIGNING_KEY)


def setup_bound():
    document,documents,generated,defenses,audit=artifacts()
    from tests.test_audit_defense_reference_states import ExactDocuments
    from jmoraIs.tenancy.context import current_tenant_context
    owner=ExactDocuments(document,current_tenant_context().tenant_id)
    trace=PostgreSQLMedicalDocumentTraceAdapter(owner)
    linked_reference=AuditDefenseTraceabilityService(trace,defenses,audit,clock=lambda:NOW).link_stage11_document(defenses.reference_for_pre_link(generated),owner.reference)
    linked=defenses.get_exact(linked_reference)
    attestor=HMACPersistedGatewayInputAttestor(KEY)
    bound=AuditDefenseGatewayInputIssuer(defenses,attestor,clock=lambda:NOW,key_reference=KEY_REF,document_trace_port=trace).issue_from_package(linked)
    return document,generated,linked,defenses,trace,attestor,bound


def test_exact_linked_package_reconstructs_and_original_attestation_verifies():
    with TenantContextBinder().bind_tenant(context()):
        document,_,linked,defenses,trace,attestor,bound=setup_bound()
        records=InMemoryPersistedGatewayInputRepository(attestor,audit_defense_query=defenses);record=records.append(bound)
        reconstructed=PersistedGatewayInputTrustService(records,attestor,{"AuditDefense":AuditDefenseGatewayInputResolver(defenses,trace)}).verify_and_resolve(record.persisted_gateway_input_id)
    assert reconstructed.dto==linked.defense
    assert reconstructed.reference.artifact_version==linked.version
    assert linked.stage11_document_reference.document_id==document.document.document_id


def test_missing_wrong_version_policy_integrity_tenant_and_stage11_fail_closed():
    binder=TenantContextBinder()
    with binder.bind_tenant(context()):
        _,_,linked,defenses,trace,_,bound=setup_bound()
        record=persisted_gateway_input_record(bound)
        resolver=AuditDefenseGatewayInputResolver(defenses,trace)
        def forbidden(*args):raise AssertionError("forbidden legacy resolution")
        defenses.history=forbidden;defenses.latest=forbidden;defenses.reference_from_upstream=forbidden
        assert resolver.resolve_exact(record)==linked.defense
        def rehash(value):return replace(value,integrity_hash=persisted_gateway_input_integrity_hash(value))
        with pytest.raises(PersistedGatewayInputError,match="LEGACY_MISSING"):
            resolver.resolve_exact(replace(record,audit_defense_reference=None))
        for field,value in (("reference_id","forged"),("package_id","forged"),("version",999),
                            ("tenant_id","other"),("policy_version","forged"),("integrity_hash","0"*64)):
            forged=replace(record,audit_defense_reference=replace(record.audit_defense_reference,**{field:value}))
            with pytest.raises(PersistedGatewayInputError):resolver.resolve_exact(forged)
            with pytest.raises(PersistedGatewayInputError):resolver.resolve_exact(rehash(forged))
        class WrongOwner:
            def __init__(self,package):self.package=package
            def get_exact(self,reference):return self.package
        for package in (replace(linked,package_id="forged"),
                        replace(linked,defense=replace(linked.defense,externally_actionable=True)),
                        replace(linked,stage11_document_reference=None),
                        replace(linked,stage11_document_reference=replace(linked.stage11_document_reference,integrity_hash="0"*64))):
            with pytest.raises(Exception):AuditDefenseGatewayInputResolver(WrongOwner(package),trace).resolve_exact(record)
        with pytest.raises(PersistedGatewayInputError):resolver.resolve_exact(bound.reference)
    with binder.bind_tenant(context("tenant-b")),pytest.raises(PersistedGatewayInputError,match="tenant"):
        resolver.resolve_exact(record)
    with pytest.raises(Exception,match="tenant context"):resolver.resolve_exact(record)


def test_typed_issuer_rejects_fabricated_nonfinal_cross_tenant_and_missing_context():
    binder=TenantContextBinder()
    with binder.bind_tenant(context()):
        _,generated,linked,defenses,trace,attestor,_=setup_bound()
        issuer=AuditDefenseGatewayInputIssuer(defenses,attestor,clock=lambda:NOW,key_reference=KEY_REF,document_trace_port=trace)
        with pytest.raises(AuditDefenseBoundaryRejected):issuer.issue_from_package(replace(linked,package_id="forged"))
        with pytest.raises(AuditDefenseBoundaryRejected):issuer.issue_from_package(replace(linked,version=999))
        with pytest.raises(AuditDefenseBoundaryRejected):issuer.issue_from_package(generated)
    with binder.bind_tenant(context("tenant-b")),pytest.raises(Exception):issuer.issue_from_package(linked)
    with pytest.raises(Exception,match="tenant context"):issuer.issue_from_package(linked)


def test_stage13_adapter_passes_typed_final_package_without_scalar_extraction():
    with TenantContextBinder().bind_tenant(context()):
        _,_,linked,defenses,trace,attestor,_=setup_bound()
        issuer=AuditDefenseGatewayInputIssuer(defenses,attestor,clock=lambda:NOW,key_reference=KEY_REF,document_trace_port=trace)
        records=InMemoryPersistedGatewayInputRepository(attestor,audit_defense_query=defenses)
        record=TypedAuditDefenseGatewayInputAdapter(issuer,records).issue_and_persist(linked)
    assert record.upstream_artifact_reference.artifact_id==linked.stream_id
    assert record.upstream_artifact_reference.artifact_version==linked.version
