from __future__ import annotations
import json
from hashlib import sha256
from jmoraIs.tenancy.context import current_tenant_context
from jmoraIs.medical_documents.domain import MedicalDocumentVersion
from jmoraIs.medical_documents.persistence import MedicalDocumentJsonCodec
from .domain import AuditDefenseBoundaryRejected,MedicalDocumentVersionReference

class PostgreSQLMedicalDocumentTraceAdapter:
    """Reference-only cross-context adapter; Medical Documents retain authority."""
    def __init__(self,repository):self._repository=repository
    def get_exact(self,reference):
        from jmoraIs.medical_documents.exact_reference import PersistedMedicalDocumentVersionReference
        if not isinstance(reference,PersistedMedicalDocumentVersionReference):
            raise AuditDefenseBoundaryRejected("owner-issued Medical Document reference is required")
        return self._repository.get_exact(reference)
    def reference_exact(self,stream_id,version):
        matches=tuple(value for value in self._repository.history(stream_id) if value.version==version)
        if len(matches)!=1:raise AuditDefenseBoundaryRejected("exact persisted MedicalDocumentVersion is required")
        value=matches[0]
        if not isinstance(value,MedicalDocumentVersion) or value.document_stream_id!=stream_id:raise AuditDefenseBoundaryRejected("persisted MedicalDocumentVersion identity mismatch")
        tenant=current_tenant_context();policies=tuple(sorted(set(value.document.policy_versions)))
        if not policies:raise AuditDefenseBoundaryRejected("MedicalDocument policy reference is required")
        integrity=sha256(json.dumps(MedicalDocumentJsonCodec().encode(value),sort_keys=True,separators=(",",":")).encode()).hexdigest()
        return MedicalDocumentVersionReference(stream_id,value.document.document_id,version,tenant.tenant_id,integrity,";".join(policies))
    def resolve_exact(self,reference):
        from jmoraIs.medical_documents.exact_reference import PersistedMedicalDocumentVersionReference
        if isinstance(reference,PersistedMedicalDocumentVersionReference):return self.get_exact(reference)
        if not isinstance(reference,MedicalDocumentVersionReference) or reference.tenant_id!=current_tenant_context().tenant_id:raise AuditDefenseBoundaryRejected("MedicalDocument tenant mismatch")
        matches=tuple(value for value in self._repository.history(reference.document_stream_id) if value.version==reference.version)
        if len(matches)!=1:raise AuditDefenseBoundaryRejected("linked MedicalDocumentVersion does not exist")
        value=matches[0]
        if value.document.document_id!=reference.document_id:raise AuditDefenseBoundaryRejected("MedicalDocument identity mismatch")
        integrity=sha256(json.dumps(MedicalDocumentJsonCodec().encode(value),sort_keys=True,separators=(",",":")).encode()).hexdigest()
        if integrity!=reference.integrity_hash:raise AuditDefenseBoundaryRejected("MedicalDocument integrity mismatch")
        policies=";".join(sorted(set(value.document.policy_versions)))
        if policies!=reference.policy_version:raise AuditDefenseBoundaryRejected("MedicalDocument policy mismatch")
        return value
