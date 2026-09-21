from __future__ import annotations

import json
from hashlib import sha256

from jmoraIs.gateway_input import UpstreamArtifactReference, issue_persisted_gateway_input
from jmoraIs.tenancy.context import current_tenant_context
from .domain import OrthopedicAssessmentSet, OrthopedicBoundaryError
from .persistence import OrthopedicJsonCodec


class OrthopedicGatewayInputIssuer:
    def __init__(self, repository, attestor, *, clock,key_reference=None): self._repository, self._attestor, self._clock,self._key_reference = repository, attestor, clock,key_reference
    def issue(self, subject_reference: str, set_id: str, version: int):
        values=tuple(v for v in self._repository.history(subject_reference) if v.set_version==version and v.set_id==set_id)
        if len(values)!=1: raise OrthopedicBoundaryError("exact persisted OrthopedicAssessmentSet is required")
        value=values[0]
        integrity=sha256(json.dumps(OrthopedicJsonCodec().encode(value),sort_keys=True,separators=(",",":")).encode()).hexdigest()
        reference=UpstreamArtifactReference("OrthopedicAssessment",set_id,version,current_tenant_context().tenant_id,integrity,value.assessment.policy_version,"orthopedic_intelligence")
        return issue_persisted_gateway_input(value.assessment,reference,self._clock(),self._attestor,self._key_reference)
