"""Focused policy/transport tests; PostgreSQL proof is separate and mandatory."""
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace
import ast
from pathlib import Path
import pytest
from jmoraIs.api.identity_security import CanonicalApiAuthorizationPolicy
from jmoraIs.api.security import CallerContext, CallerRole, PurposeOfUse
from jmoraIs.api.workspace_launch import (
    ClinicalWorkspaceLaunchService, LaunchReferences, LaunchRejected,
    PersistedClinicalWorkspaceLaunchReference, canonical_launch, launch_digest,
)
from jmoraIs.api.workspace_schemas import ClinicalStateReferenceTransport
from jmoraIs.infrastructure.workspace_launch import verify_launch_row
from jmoraIs.tenancy.context import TenantContextBinder


class Repository:
    def __init__(self): self.saved = None
    def append(self, launch): self.saved = launch
    def get_exact(self, reference):
        if self.saved is None or reference.integrity_hash != launch_digest(self.saved):
            raise LaunchRejected('launch unavailable')
        return self.saved


def setup():
    caller = CallerContext('doctor', CallerRole.CLINICAL_REVIEWER, PurposeOfUse.CLINICAL_REVIEW,
        'correlation', 'policy', organization_id='organization', tenant_id='tenant', principal_type='HUMAN')
    reference = ClinicalStateReferenceTransport(reference_id='owner-ref', state_id='state', state_version=1,
        pseudonymous_patient_id='pseudonym', tenant_id='tenant', policy_version='policy',
        predecessor_reference_id=None, predecessor_state_version=None, provenance_reference='provenance',
        state_integrity_hash='a'*64, integrity_hash='b'*64, issued_at=datetime.now(timezone.utc))
    exact = reference.to_reference()
    seen = []
    def validate(candidate):
        if candidate != exact: raise LaunchRejected('rejected exact owner reference')
        seen.append(candidate)
    repository = Repository()
    service = ClinicalWorkspaceLaunchService(repository, CanonicalApiAuthorizationPolicy(),
        SimpleNamespace(clinical_summary=validate), None)
    return caller, reference, repository, service, seen


def test_prospective_binding_unchanged_and_owner_validation():
    caller, ref, repo, service, seen = setup()
    binder = TenantContextBinder()
    with binder.bind(caller):
        exact = service.create(caller, LaunchReferences(summary=ref))
        assert isinstance(exact, PersistedClinicalWorkspaceLaunchReference)
        launch = service.get_exact(caller, exact)
        assert launch.references.summary == ref and len(seen)==2
        assert launch.principal_id == caller.caller_id
        assert set(type(launch).model_fields) == {'launch_id','version','tenant_id','organization_id','principal_id','purpose','policy_version','created_at','correlation_id','references'}
        for field, value in [('reference_id','fabricated'),('tenant_id','other')]:
            with pytest.raises(Exception): service.create(caller, LaunchReferences(summary=ref.model_copy(update={field:value})))
        assert repo.saved == launch
        with pytest.raises(Exception): service.get_exact(caller, exact.model_copy(update={'integrity_hash':'0'*64}))
    with pytest.raises(Exception): service.get_exact(caller, exact)


@pytest.mark.parametrize('field,value', [('caller_id','other'),('tenant_id','other'),('organization_id','other'),
    ('policy_version','other'),('purpose',PurposeOfUse.ADMINISTRATION),('role',CallerRole.INTERNAL_SERVICE),('principal_type','SERVICE')])
def test_wrong_binding_denied(field,value):
    caller, ref, repo, service, seen = setup()
    binder=TenantContextBinder()
    with binder.bind(caller): exact=service.create(caller,LaunchReferences(summary=ref))
    other=replace(caller,**{field:value})
    with binder.bind(other),pytest.raises(Exception): service.get_exact(other,exact)


def test_empty_is_explicit_and_checkpoint_recomputes_payload():
    caller, ref, repo, service, seen=setup()
    with TenantContextBinder().bind(caller):
        exact=service.create(caller,LaunchReferences())
        launch=service.get_exact(caller,exact)
    assert not seen and all(v is None for v in launch.references.model_dump().values())
    row=dict(launch_id=launch.launch_id,tenant_id=launch.tenant_id,payload=canonical_launch(launch),
             integrity_hash=launch_digest(launch),created_at=launch.created_at)
    assert verify_launch_row(row,[(1,launch_digest(launch))])==launch
    for checkpoints in ([],[(2,launch_digest(launch))],[(1,'0'*64)],[(1,launch_digest(launch))]*2):
        with pytest.raises(LaunchRejected): verify_launch_row(row,checkpoints)
    for tampered in (None,{**row,'tenant_id':'other'},{**row,'payload':row['payload'].replace('doctor','forged')}):
        with pytest.raises(LaunchRejected): verify_launch_row(tampered,[(1,launch_digest(launch))])


def test_no_fallback_or_reference_reissuance():
    source=Path('jmoraIs/api/workspace_launch.py').read_text()
    attrs={n.attr for n in ast.walk(ast.parse(source)) if isinstance(n,ast.Attribute)}
    assert not attrs & {'latest','history','at','reference_for','timeline_reference_for'}
