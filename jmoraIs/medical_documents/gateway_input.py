from __future__ import annotations

import json
from hashlib import sha256

from jmoraIs.gateway_input import (
    UpstreamArtifactReference, issue_persisted_gateway_input,
)
from jmoraIs.tenancy.context import current_tenant_context

from .domain import DocumentBoundaryRejected, MedicalDocumentVersion
from .persistence import MedicalDocumentJsonCodec


class MedicalDocumentGatewayInputIssuer:
    def __init__(self, repository, attestor, *, clock, key_reference=None):
        self._repository, self._attestor, self._clock, self._key_reference = repository, attestor, clock, key_reference

    def issue(self, stream_id: str, version: int):
        values = tuple(v for v in self._repository.history(stream_id) if v.version == version)
        if len(values) != 1:
            raise DocumentBoundaryRejected("exact persisted MedicalDocumentVersion is required")
        value = values[0]
        if not isinstance(value, MedicalDocumentVersion) or value.document_stream_id != stream_id:
            raise DocumentBoundaryRejected("persisted medical-document identity mismatch")
        if not value.document.validation.valid:
            raise DocumentBoundaryRejected("invalid medical document is not gateway eligible")
        tenant = current_tenant_context()
        integrity = sha256(json.dumps(MedicalDocumentJsonCodec().encode(value), sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        policies = tuple(sorted(set(value.document.policy_versions)))
        if not policies:
            raise DocumentBoundaryRejected("medical-document policy reference is required")
        reference = UpstreamArtifactReference("MedicalDocument", stream_id, version, tenant.tenant_id,
            integrity, ";".join(policies), "medical_documents")
        return issue_persisted_gateway_input(value.document, reference, self._clock(), self._attestor,self._key_reference)
