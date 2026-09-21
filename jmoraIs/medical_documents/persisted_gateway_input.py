from __future__ import annotations
import json
from hashlib import sha256
from jmoraIs.gateway_input import PersistedGatewayInputError,UpstreamArtifactReference
from .domain import MedicalDocumentVersion
from .persistence import MedicalDocumentJsonCodec

class MedicalDocumentGatewayInputResolver:
    def __init__(self,repository):self._repository=repository
    def resolve_exact(self,reference):
        if not isinstance(reference,UpstreamArtifactReference) or reference.artifact_type!="MedicalDocument":raise PersistedGatewayInputError("MedicalDocument upstream type mismatch")
        matches=tuple(v for v in self._repository.history(reference.artifact_id) if v.version==reference.artifact_version)
        if len(matches)!=1:raise PersistedGatewayInputError("exact MedicalDocumentVersion is unavailable")
        value=matches[0]
        if not isinstance(value,MedicalDocumentVersion):raise PersistedGatewayInputError("MedicalDocument identity mismatch")
        integrity=sha256(json.dumps(MedicalDocumentJsonCodec().encode(value),sort_keys=True,separators=(",",":")).encode()).hexdigest()
        if integrity!=reference.integrity_reference:raise PersistedGatewayInputError("MedicalDocument integrity mismatch")
        if ";".join(sorted(set(value.document.policy_versions)))!=reference.policy_version:raise PersistedGatewayInputError("MedicalDocument policy mismatch")
        return value.document
