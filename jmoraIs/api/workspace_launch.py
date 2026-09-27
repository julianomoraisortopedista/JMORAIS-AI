"""Prospective authorization boundary; never an issuer of clinical references."""
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Literal
from uuid import uuid4

from pydantic import AwareDatetime, Field
from jmoraIs.tenancy.context import current_tenant_context
from .schemas import ApiModel
from .workspace_schemas import (
    ClinicalStateReferenceTransport, PersistedClinicalStateTimelineReferenceTransport,
    PersistedGovernedEvidenceReferenceTransport, PersistedClinicalReasoningInputReferenceTransport,
    PersistedMedicalDocumentVersionReferenceTransport, PersistedHumanReviewReferenceTransport,
    PersistedDefensePackageReferenceTransport,
)


class LaunchRejected(RuntimeError):
    pass


class LaunchReferences(ApiModel):
    summary: ClinicalStateReferenceTransport | None = None
    timeline: PersistedClinicalStateTimelineReferenceTransport | None = None
    evidence: PersistedGovernedEvidenceReferenceTransport | None = None
    explainability: PersistedClinicalReasoningInputReferenceTransport | None = None
    medical_document: PersistedMedicalDocumentVersionReferenceTransport | None = None
    human_review: PersistedHumanReviewReferenceTransport | None = None
    audit_defense: PersistedDefensePackageReferenceTransport | None = None


class ClinicalWorkspaceLaunch(ApiModel):
    launch_id: str = Field(min_length=1, max_length=80)
    version: Literal[1] = 1
    tenant_id: str = Field(min_length=1)
    organization_id: str = Field(min_length=1)
    principal_id: str = Field(min_length=1)
    purpose: Literal['CLINICAL_REVIEW'] = 'CLINICAL_REVIEW'
    policy_version: str = Field(min_length=1)
    created_at: AwareDatetime
    correlation_id: str = Field(min_length=1)
    references: LaunchReferences


class PersistedClinicalWorkspaceLaunchReference(ApiModel):
    launch_id: str = Field(min_length=1, max_length=80)
    version: Literal[1] = 1
    tenant_id: str = Field(min_length=1)
    integrity_hash: str = Field(pattern=r'^[a-f0-9]{64}$')


class WorkspaceBootstrapRequest(ApiModel):
    reference: PersistedClinicalWorkspaceLaunchReference


class WorkspaceBootstrapResponse(ApiModel):
    references: LaunchReferences


def canonical_launch(launch):
    return json.dumps(launch.model_dump(mode='json'), ensure_ascii=False,
                      sort_keys=True, separators=(',', ':'))


def launch_digest(launch):
    return sha256(canonical_launch(launch).encode('utf-8')).hexdigest()


class ClinicalWorkspaceLaunchService:
    """Only producer. Called by trusted application composition, never a write route.

    Authorization is for the authenticated principal itself, not delegated grants.
    The existing IAM policy and active TenantContext remain mandatory on every call.
    """
    def __init__(self, repository, authorization, workspace, remaining_workspace):
        self._repository = repository
        self._authorization = authorization
        self._workspace = workspace
        self._remaining = remaining_workspace

    def _authorize(self, caller):
        self._authorization.authorize(caller, 'WORKSPACE_READ')
        tenant = current_tenant_context()
        if (caller.principal_type != 'HUMAN' or caller.purpose.value != 'CLINICAL_REVIEW'
            or (tenant.tenant_id, tenant.organization_id, tenant.principal_id,
                tenant.purpose, tenant.policy_version) !=
               (caller.tenant_id, caller.organization_id, caller.caller_id,
                caller.purpose.value, caller.policy_version)):
            raise LaunchRejected('launch authorization rejected')
        return tenant

    def _validate(self, references):
        tenant = current_tenant_context()
        for name, target, method in (
            ('summary', self._workspace, 'clinical_summary'),
            ('timeline', self._remaining, 'timeline'),
            ('evidence', self._workspace, 'evidence'),
            ('explainability', self._workspace, 'explainability'),
            ('medical_document', self._remaining, 'medical_document'),
            ('human_review', self._remaining, 'human_review'),
            ('audit_defense', self._remaining, 'audit_defense'),
        ):
            value = getattr(references, name)
            if value is None:
                continue
            if value.tenant_id != tenant.tenant_id:
                raise LaunchRejected('launch reference rejected')
            # These approved viewer methods validate through the exact owner ports.
            getattr(target, method)(value.to_reference())

    def create(self, caller, references: LaunchReferences):
        self._authorize(caller)
        if not isinstance(references, LaunchReferences):
            raise LaunchRejected('typed launch references required')
        self._validate(references)
        launch = ClinicalWorkspaceLaunch(launch_id='cwl_' + uuid4().hex,
            tenant_id=caller.tenant_id, organization_id=caller.organization_id,
            principal_id=caller.caller_id, policy_version=caller.policy_version,
            created_at=datetime.now(timezone.utc), correlation_id=caller.correlation_id,
            references=references)
        self._repository.append(launch)
        return PersistedClinicalWorkspaceLaunchReference(launch_id=launch.launch_id,
            tenant_id=launch.tenant_id, integrity_hash=launch_digest(launch))

    def get_exact(self, caller, reference):
        self._authorize(caller)
        if not isinstance(reference, PersistedClinicalWorkspaceLaunchReference):
            raise LaunchRejected('typed launch reference required')
        if reference.tenant_id != caller.tenant_id:
            raise LaunchRejected('launch unavailable')
        launch = self._repository.get_exact(reference)
        if (launch.principal_id, launch.organization_id, launch.policy_version, launch.purpose) != (
            caller.caller_id, caller.organization_id, caller.policy_version, caller.purpose.value):
            raise LaunchRejected('launch unavailable')
        self._validate(launch.references)
        return launch
