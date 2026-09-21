from dataclasses import replace

import pytest

from jmoraIs.audit_defense import AuditDefenseTraceabilityService,PostgreSQLMedicalDocumentTraceAdapter
from jmoraIs.audit_defense.review_governance import AuditDefenseReviewGovernanceAdapter
from jmoraIs.audit_defense import AuditDefenseGatewayInputIssuer
from jmoraIs.clinical import HumanReviewStatus
from jmoraIs.gateway_input import HMACPersistedGatewayInputAttestor
from jmoraIs.llm_human_review import LLMHumanReviewRejected,MedicalDocumentReviewGovernanceAdapter,UpstreamReviewGovernanceRouter
from jmoraIs.secrets.domain import KeyReference,SecretPurpose
from jmoraIs.tenancy.context import TenantContextBinder
from tests.test_audit_defense import NOW
from tests.test_audit_defense import setup as defense_setup
from tests.test_audit_defense_gateway_input_resolver import KEY,setup_bound
from tests.test_guideline_engine import ready_input
from tests.test_stage11_stage12_traceability import artifacts,context


def _adapter():
    document,_,linked,repository,trace,_,bound=setup_bound()
    reference=repository.reference_for(linked)
    return AuditDefenseReviewGovernanceAdapter(repository,trace),repository,reference,bound.reference,linked,document


def test_exact_owner_reference_projects_constraints_and_router_dispatches():
    with TenantContextBinder().bind_tenant(context()):
        adapter,_,_,upstream,linked,_=_adapter()
        constraints=adapter.constraints(upstream)
        router=UpstreamReviewGovernanceRouter({"AuditDefense":adapter})
        assert router.constraints(upstream)==constraints
        expected=tuple(sorted({x.limitation_id for a in linked.defense.arguments for x in a.limitations if x.severity.value=="CRITICAL"}))
        assert constraints.critical_conflicts==expected and constraints.generated_by==linked.reviewer_id


def test_mismatch_fabrication_policy_integrity_tenant_and_missing_context_fail_closed():
    binder=TenantContextBinder()
    with binder.bind_tenant(context()):
        adapter,repository,reference,upstream,_,_=_adapter()
        for bad in (replace(upstream,artifact_type="MedicalDocument"),replace(upstream,artifact_version=999),
                    replace(upstream,policy_version="forged"),replace(upstream,integrity_reference="0"*64)):
            with pytest.raises(LLMHumanReviewRejected):adapter.constraints(bad)
        repository._references.pop(reference.reference_id)
        with pytest.raises(LLMHumanReviewRejected):adapter.constraints(upstream)
    with binder.bind_tenant(context("tenant-b")),pytest.raises(LLMHumanReviewRejected):adapter.constraints(upstream)
    with pytest.raises(Exception,match="tenant context"):adapter.constraints(upstream)


def test_medical_document_adapter_remains_separate():
    with TenantContextBinder().bind_tenant(context()):
        audit_adapter,_,_,upstream,_,document=_adapter()
        router=UpstreamReviewGovernanceRouter({"AuditDefense":audit_adapter,"MedicalDocument":MedicalDocumentReviewGovernanceAdapter(object())})
        assert router.constraints(upstream)==audit_adapter.constraints(upstream)


def test_critical_conflicts_and_canonical_reviewer_attribution_are_not_downgraded():
    binder=TenantContextBinder()
    with binder.bind_tenant(context()):
        document,documents,_,_,_=artifacts()
        from tests.test_audit_defense_reference_states import ExactDocuments
        document_owner=ExactDocuments(document,context().tenant_id)
        trace=PostgreSQLMedicalDocumentTraceAdapter(document_owner)
        inp=ready_input();inp=replace(inp,quality=replace(inp.quality,conflicting_data_references=("conflict:canonical",)))
        service,repository,audit,_=defense_setup(input_value=inp)
        initial=service.generate(inp)
        linked=AuditDefenseTraceabilityService(trace,repository,audit,clock=lambda:NOW).link_stage11_document(
            repository.reference_for_pre_link(initial),document_owner.reference)
        linked=repository.get_exact(linked)
        attestor=HMACPersistedGatewayInputAttestor(KEY)
        key=KeyReference("memory","review-governance","v1",SecretPurpose.SIGNING_KEY)
        repository.reference_for(linked)
        upstream=AuditDefenseGatewayInputIssuer(repository,attestor,clock=lambda:NOW,key_reference=key,document_trace_port=trace).issue_from_package(linked).reference
        constraints=AuditDefenseReviewGovernanceAdapter(repository,trace).constraints(upstream)
        assert constraints.critical_conflicts
        assert constraints.generated_by is None

        normal_service,normal_repository,normal_audit,normal_input=defense_setup()
        normal=normal_service.generate(normal_input)
        normal_linked=AuditDefenseTraceabilityService(trace,normal_repository,normal_audit,clock=lambda:NOW).link_stage11_document(
            normal_repository.reference_for_pre_link(normal),document_owner.reference)
        normal_linked=normal_repository.get_exact(normal_linked)
        reviewed=normal_service.submit_for_review(normal_linked.stream_id,reviewer_id="reviewer",target=HumanReviewStatus.APPROVED_BY_REVIEWER,justification="canonical review")
        normal_repository.reference_for(reviewed)
        reviewed_upstream=AuditDefenseGatewayInputIssuer(normal_repository,attestor,clock=lambda:NOW,key_reference=key,document_trace_port=trace).issue_from_package(reviewed).reference
        assert AuditDefenseReviewGovernanceAdapter(normal_repository,trace).constraints(reviewed_upstream).generated_by=="reviewer"
