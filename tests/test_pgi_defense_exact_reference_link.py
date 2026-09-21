import ast
import inspect
from dataclasses import replace

import pytest

from jmoraIs.gateway_input import PersistedGatewayInputError, persisted_gateway_input_record, persisted_gateway_input_integrity_hash
from jmoraIs.infrastructure.persisted_gateway_input import InMemoryPersistedGatewayInputRepository, PersistedGatewayInputTrustService, _encode, _decode
from jmoraIs.audit_defense.gateway_input import AuditDefenseGatewayInputIssuer
from jmoraIs.tenancy.context import TenantContextBinder
from tests.test_audit_defense_gateway_input_resolver import setup_bound
from tests.test_stage11_stage12_traceability import context


def test_same_typed_reference_metadata_roundtrip_and_legacy_fail_closed():
    with TenantContextBinder().bind_tenant(context()):
        _,_,_,owner,_,attestor,bound=setup_bound()
        records=InMemoryPersistedGatewayInputRepository(attestor,audit_defense_query=owner)
        record=records.append(bound)
        assert record.audit_defense_reference is bound.audit_defense_reference
        assert _decode(_encode(record))==record
        assert "defense" not in _encode(record)
        legacy=persisted_gateway_input_record(replace(bound,audit_defense_reference=None))
        assert legacy.audit_defense_linkage_status=="LEGACY_MISSING_PERSISTED_DEFENSE_PACKAGE_REFERENCE"
        assert persisted_gateway_input_integrity_hash(legacy)==legacy.integrity_hash
        class HistoricalRecords:
            def get(self,identifier):return legacy
        with pytest.raises(PersistedGatewayInputError,match="LEGACY_MISSING"):
            PersistedGatewayInputTrustService(HistoricalRecords(),attestor,{}).verify_and_resolve(legacy.persisted_gateway_input_id)
        with pytest.raises(PersistedGatewayInputError,match="LEGACY_MISSING"):
            records.append(replace(bound,audit_defense_reference=None))
        with pytest.raises(Exception):
            records.append(replace(bound,audit_defense_reference=replace(bound.audit_defense_reference,reference_id="forged")))


def test_canonical_issuance_transports_owner_reference_without_historical_resolution():
    import textwrap
    tree=ast.parse(textwrap.dedent(inspect.getsource(AuditDefenseGatewayInputIssuer.issue_from_package)))
    calls={node.func.attr for node in ast.walk(tree) if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute)}
    assert "get_exact" in calls
    assert not calls & {"history","latest","reference_from_upstream","_exact"}
    with TenantContextBinder().bind_tenant(context()):
        _,_,package,owner,trace,attestor,bound=setup_bound()
        def forbidden(*args):raise AssertionError("legacy trust path")
        owner.history=forbidden;owner.latest=forbidden
        issuer=AuditDefenseGatewayInputIssuer(owner,attestor,clock=lambda:bound.resolved_at,key_reference=bound.attestation_key_reference,document_trace_port=trace)
        result=issuer.issue_from_package(package,persisted_reference=bound.audit_defense_reference)
        assert result.audit_defense_reference is bound.audit_defense_reference
