"""Independent IAM and owner policy domains in one exact, authorized launch."""
from dataclasses import replace
from uuid import uuid4

import pytest
from fastapi.encoders import jsonable_encoder
from sqlalchemy import text

from jmoraIs.api.security import CallerCredentials
from jmoraIs.api.workspace_launch import LaunchReferences, LaunchRejected
from jmoraIs.appraisal.exact_reference import GovernedEvidenceReferenceRejected, reference_integrity
from jmoraIs.llm_gateway.exact_reference import LLMInvocationReferenceRejected, llm_invocation_reference_integrity
from jmoraIs.llm_gateway.exact_reference_persistence import PostgreSQLLLMInvocationExactReferenceRepository
from jmoraIs.tenancy.context import TenantContextBinder
from tests.test_evidence_lifecycle_authority_postgresql import authority
from tests import test_clinical_workspace_postgresql as core
from tests import test_clinical_workspace_remaining_postgresql as remaining
from tests import test_governed_llm_draft_exact_reference_postgresql as draft
from tests import test_workspace_runtime_api as runtime


def test_independent_owner_policies_and_authenticated_launch(authority, monkeypatch):
    owner, writer, tenant, packages, appraisals, lifecycle, evidence, repository, reference = authority
    _, canonical, _ = runtime.compose(owner.url.render_as_string(hide_password=False), tenant.policy_version, False, monkeypatch)
    def issue(owner, writer, suffix, tenant):
        return draft.persisted_draft(owner, writer, suffix, tenant, draft_attestor=canonical.draft_attestor)
    monkeypatch.setattr(remaining.review_source, 'persisted_draft', issue)
    core_reference = core.seed(owner, writer, tenant, uuid4().hex)
    rest = remaining.seed(owner, writer, tenant, uuid4().hex)
    references = LaunchReferences.model_validate(jsonable_encoder(dict(summary=core_reference.clinical_state_reference,
        evidence=core_reference.governed_evidence_references[0], explainability=core_reference,
        timeline=rest[0], medical_document=rest[1], human_review=rest[2], audit_defense=rest[4])))
    invocation_ref = rest[2].draft_reference.invocation_reference
    assert references.evidence.policy_version == 'ST-02'
    assert invocation_ref.policy_version == 'MIP-10.1'
    assert tenant.policy_version not in ('ST-02','MIP-10.1')
    invocations = PostgreSQLLLMInvocationExactReferenceRepository(writer)
    assert invocations.get_exact(invocation_ref).policy_version == 'MIP-10.1'
    forged = replace(invocation_ref, policy_version='ST-02')
    forged = replace(forged, integrity_hash=llm_invocation_reference_integrity(forged))
    with pytest.raises(LLMInvocationReferenceRejected):invocations.get_exact(forged)
    for change in (dict(policy_version='MIP-10.1'), dict(provenance_reference='forged'), dict(governed_evidence_integrity_hash='0'*64)):
        bad = replace(reference, **change)
        bad = replace(bad, integrity_hash=reference_integrity(bad))
        with pytest.raises(GovernedEvidenceReferenceRejected):repository.get_exact(bad)
    before = references.model_dump_json()
    auth, _ = runtime.token(owner, tenant)
    caller = canonical.operational_services.authentication.authenticate(
        CallerCredentials(auth['authorization'][7:],'CLINICAL_REVIEW'),uuid4().hex)
    binder = TenantContextBinder()
    with binder.bind(caller):
        launch = canonical.launch_producer.create(caller, references)
        assert canonical.launch_service.get_exact(caller,launch).references.model_dump_json() == before
    for field, value in (('caller_id','other'),('organization_id','other'),('tenant_id','other'),('policy_version','other')):
        other = replace(caller, **{field:value})
        with binder.bind(other), pytest.raises(LaunchRejected):canonical.launch_service.get_exact(other,launch)
    for kwargs in (dict(role='service'),dict(allowed=('INTERNAL_OPERATIONS',))):
        denied, _ = runtime.token(owner,tenant,**kwargs)
        with pytest.raises(Exception):
            candidate = canonical.operational_services.authentication.authenticate(
                CallerCredentials(denied['authorization'][7:],'CLINICAL_REVIEW'),uuid4().hex)
            with binder.bind(candidate):canonical.launch_service.get_exact(candidate,launch)
    canonical.database_credentials.close()
