from pathlib import Path

ROOT=Path(__file__).parents[1]


def test_owner_resolver_isolated_from_gateway_and_exact_version_only():
    resolver=(ROOT/"jmoraIs/audit_defense/persisted_gateway_input.py").read_text()
    gateway=(ROOT/"jmoraIs/llm_gateway/application.py").read_text()
    assert "class AuditDefenseGatewayInputResolver" in resolver
    assert "self._repository.get_exact(exact)" in resolver
    assert "record.audit_defense_reference" in resolver
    assert "history(" not in resolver
    assert "reference_from_upstream(" not in resolver
    assert "latest(" not in resolver
    assert "AuditDefenseGatewayInputResolver" not in gateway
    assert "PostgreSQLAuditDefenseRepository" not in gateway
    assert "evaluation" not in resolver

def test_canonical_issuer_and_e2e_adapter_accept_typed_package_not_scalars():
    issuer=(ROOT/"jmoraIs/audit_defense/gateway_input.py").read_text()
    adapters=(ROOT/"evaluation/e2e_acceptance/adapters.py").read_text()
    canonical=issuer[issuer.index("def issue_from_package"):issuer.index("def issue(")]
    adapter=adapters[adapters.index("class TypedAuditDefenseGatewayInputAdapter"):]
    signature=canonical.splitlines()[0]
    assert "package:DefensePackage" in signature
    assert "stream_id" not in signature and "version:" not in signature
    assert "issue_from_package(final_package)" in adapter
    assert ".issue(" not in adapter
    assert "reference_id" not in adapter and "preceding.version" not in adapter

def test_exact_reference_is_owner_side_and_e2e_only_transports_it():
    domain=(ROOT/"jmoraIs/audit_defense/domain.py").read_text()
    persistence=(ROOT/"jmoraIs/audit_defense/persistence.py").read_text()
    adapter=(ROOT/"evaluation/e2e_acceptance/adapters.py").read_text()
    gateway=(ROOT/"jmoraIs/llm_gateway/application.py").read_text()
    assert "class PersistedDefensePackageReference" in domain
    assert "def reference_for(" in persistence and "def get_exact(" in persistence
    block=adapter[adapter.index("class TypedAuditDefenseGatewayInputAdapter"):]
    assert "get_exact(persisted_reference)" in block
    assert ".stream_id" not in block and ".version" not in block and "latest(" not in block
    assert "audit_defense.persistence" not in gateway

def test_real_stage13_uses_exact_audit_defense_handoff_without_legacy_discovery():
    stage13=(ROOT/"tests/test_stage13_real_service_postgresql.py").read_text()
    assert "reference_for(final_package)" in stage13
    assert "get_exact(persisted_defense_reference)" in stage13
    assert "issue_from_package(exact_final_package)" in stage13
    assert "MedicalDocumentGatewayInputIssuer" not in stage13
    assert "latest(" not in stage13
