from __future__ import annotations

import json
from hashlib import sha256

from jmoraIs.gateway_input import PersistedGatewayInputError, PersistedGatewayInputRecord, persisted_gateway_input_integrity_hash
from jmoraIs.tenancy.context import current_tenant_context

from .domain import DefensePackage, PersistedDefensePackageReference, AuditDefenseBoundaryRejected
from .persistence import AuditDefenseJsonCodec


class AuditDefenseGatewayInputResolver:
    """Exact owner-side reconstruction for an attested AuditDefense Gateway input."""

    def __init__(self, repository, document_trace_port):
        self._repository = repository
        self._documents = document_trace_port

    def resolve_exact(self, record):
        if not isinstance(record, PersistedGatewayInputRecord):
            raise PersistedGatewayInputError("persisted AuditDefense Gateway record is required")
        exact=record.audit_defense_reference
        if not isinstance(exact,PersistedDefensePackageReference):
            raise PersistedGatewayInputError("LEGACY_MISSING_PERSISTED_DEFENSE_PACKAGE_REFERENCE")
        if persisted_gateway_input_integrity_hash(record)!=record.integrity_hash:
            raise PersistedGatewayInputError("persisted Gateway record integrity mismatch")
        reference=record.upstream_artifact_reference
        if reference.artifact_type != "AuditDefense" or reference.source_context != "audit_defense":
            raise PersistedGatewayInputError("AuditDefense upstream type or source mismatch")
        if reference.tenant_id != current_tenant_context().tenant_id:
            raise PersistedGatewayInputError("AuditDefense tenant mismatch")
        if reference.artifact_version < 1:
            raise PersistedGatewayInputError("AuditDefense version is invalid")

        if (exact.stream_id,exact.version,exact.tenant_id,exact.policy_version,exact.integrity_hash)!=(reference.artifact_id,reference.artifact_version,reference.tenant_id,reference.policy_version,reference.integrity_reference):
            raise PersistedGatewayInputError("AuditDefense exact reference consistency mismatch")
        try:
            package=self._repository.get_exact(exact)
        except AuditDefenseBoundaryRejected as exc:
            raise PersistedGatewayInputError("AuditDefense owner reference rejected") from exc
        if not isinstance(package,DefensePackage) or (package.stream_id,package.version,package.package_id)!=(exact.stream_id,exact.version,exact.package_id):
            raise PersistedGatewayInputError("DefensePackage identity mismatch")
        if package.stage11_document_reference is None:
            raise PersistedGatewayInputError("DefensePackage Stage-11 reference is required")

        # The Medical Document bounded context remains authoritative. This exact
        # resolution validates tenant, document identity/version, policy and hash.
        self._documents.resolve_exact(package.stage11_document_reference)

        policies = ";".join(sorted(set(package.defense.explainability.policy_versions)))
        if not policies or policies != reference.policy_version:
            raise PersistedGatewayInputError("AuditDefense policy mismatch")
        integrity = sha256(json.dumps(
            AuditDefenseJsonCodec().encode(package), sort_keys=True,
            separators=(",", ":"),
        ).encode()).hexdigest()
        if integrity != reference.integrity_reference:
            raise PersistedGatewayInputError("DefensePackage integrity mismatch")
        return package.defense
