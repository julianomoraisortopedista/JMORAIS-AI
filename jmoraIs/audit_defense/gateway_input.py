from __future__ import annotations

import json
from hashlib import sha256

from jmoraIs.gateway_input import UpstreamArtifactReference, issue_persisted_gateway_input
from jmoraIs.tenancy.context import current_tenant_context
from .domain import AuditDefenseBoundaryRejected, DefensePackage
from .persistence import AuditDefenseJsonCodec


class AuditDefenseGatewayInputIssuer:
    def __init__(self, repository, attestor, *, clock,key_reference=None,document_trace_port=None):
        self._repository,self._attestor,self._clock,self._key_reference=repository,attestor,clock,key_reference
        self._documents=document_trace_port

    def issue_from_package(self,package:DefensePackage,*,persisted_reference=None):
        """Canonical governed path: identity is derived from a typed persisted handoff."""
        if not isinstance(package,DefensePackage):raise AuditDefenseBoundaryRejected("typed DefensePackage handoff is required")
        exact_reference=persisted_reference if persisted_reference is not None else self._repository.reference_for(package)
        persisted=self._repository.get_exact(exact_reference)
        if persisted!=package:raise AuditDefenseBoundaryRejected("DefensePackage handoff does not match canonical persistence")
        if persisted.stage11_document_reference is None:raise AuditDefenseBoundaryRejected("final Stage-11-linked DefensePackage is required")
        if self._documents is None:raise AuditDefenseBoundaryRejected("canonical Stage-11 trace port is required")
        self._documents.resolve_exact(persisted.stage11_document_reference)
        return self._issue(persisted,exact_reference)

    def issue(self, stream_id: str, version: int):
        """Legacy scalar compatibility; not canonical for governed Stage-13 flow."""
        value=self._exact(stream_id,version)
        return self._issue(value)

    def _exact(self,stream_id,version):
        history=self._repository.history(stream_id)
        values=tuple(v for v in history if v.version==version)
        if len(values)!=1:raise AuditDefenseBoundaryRejected("exact persisted DefensePackage is required")
        value=values[0]
        if not isinstance(value,DefensePackage) or value.stream_id!=stream_id: raise AuditDefenseBoundaryRejected("persisted audit-defense identity mismatch")
        for index,item in enumerate(history,1):
            expected_previous=None if index==1 else history[index-2].package_id
            if item.stream_id!=stream_id or item.version!=index or item.previous_package_id!=expected_previous:
                raise AuditDefenseBoundaryRejected("persisted DefensePackage version chain is invalid")
        return value

    def _issue(self,value,exact_reference=None):
        policies=tuple(sorted(set(value.defense.explainability.policy_versions)))
        if not policies: raise AuditDefenseBoundaryRejected("audit-defense policy reference is required")
        integrity=sha256(json.dumps(AuditDefenseJsonCodec().encode(value),sort_keys=True,separators=(",",":")).encode()).hexdigest()
        reference=UpstreamArtifactReference("AuditDefense",value.stream_id,value.version,current_tenant_context().tenant_id,integrity,";".join(policies),"audit_defense")
        return issue_persisted_gateway_input(value.defense,reference,self._clock(),self._attestor,self._key_reference,audit_defense_reference=exact_reference)
