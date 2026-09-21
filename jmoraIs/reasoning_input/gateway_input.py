from __future__ import annotations

import json
from hashlib import sha256

from jmoraIs.gateway_input import UpstreamArtifactReference, issue_persisted_gateway_input
from jmoraIs.tenancy.context import current_tenant_context
from .domain import ClinicalReasoningInput, InvalidReasoningInput
from .persistence import ReasoningInputJsonCodec


class ClinicalReasoningGatewayInputIssuer:
    def __init__(self, repository, attestor, *, clock,key_reference=None): self._repository, self._attestor, self._clock,self._key_reference = repository, attestor, clock,key_reference
    def issue(self, input_id: str):
        value=self._repository.get(input_id)
        if not isinstance(value,ClinicalReasoningInput) or value.input_id!=input_id: raise InvalidReasoningInput("exact persisted ClinicalReasoningInput is required")
        integrity=sha256(json.dumps(ReasoningInputJsonCodec().encode(value),sort_keys=True,separators=(",",":")).encode()).hexdigest()
        policies=tuple(sorted({x.policy_version for x in value.policy_versions}))
        if not policies: raise InvalidReasoningInput("reasoning-input policy reference is required")
        reference=UpstreamArtifactReference("ClinicalReasoningInput",input_id,value.input_version,current_tenant_context().tenant_id,integrity,";".join(policies),"reasoning_input")
        return issue_persisted_gateway_input(value,reference,self._clock(),self._attestor,self._key_reference)
