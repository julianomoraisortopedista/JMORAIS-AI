from .domain import *
class InMemoryAuditDefenseRepository:
    def __init__(self):self._streams={};self._ids=set();self._references={};self._tenants={}
    def append(self,value):
        _validate_document_reference(value.stage11_document_reference)
        if value.package_id in self._ids:raise AuditDefenseVersionConflict("defense history is append-only")
        history=self._streams.get(value.stream_id,())
        if history and (value.version!=history[-1].version+1 or value.previous_package_id!=history[-1].package_id):raise AuditDefenseVersionConflict("invalid defense version chain")
        if not history and (value.version!=1 or value.previous_package_id is not None):raise AuditDefenseVersionConflict("defense history must begin at version 1")
        if history and history[-1].stage11_document_reference is not None and value.stage11_document_reference!=history[-1].stage11_document_reference:
            raise AuditDefenseBoundaryRejected("Stage-11 linkage cannot be removed or replaced")
        from jmoraIs.tenancy.context import current_tenant_context
        from jmoraIs.tenancy.domain import MissingTenantContext
        try:tenant=current_tenant_context().tenant_id
        except MissingTenantContext:tenant=None
        if history and self._tenants.get(history[-1].package_id)!=tenant:
            raise AuditDefenseBoundaryRejected("DefensePackage tenant mismatch")
        self._tenants[value.package_id]=tenant
        self._ids.add(value.package_id);self._streams.setdefault(value.stream_id,[]).append(value)
    def latest(self,stream_id):
        values=self.history(stream_id);return values[-1] if values else None
    def history(self,stream_id):return tuple(self._streams.get(stream_id,()))
    def reference_for(self,value):
        return self._issue_reference(value,DefenseReferenceState.STAGE11_LINKED)
    def reference_for_pre_link(self,value):
        return self._issue_reference(value,DefenseReferenceState.PRE_LINK)
    def _issue_reference(self,value,state):
        from datetime import timezone
        from hashlib import sha256
        from uuid import uuid4
        import json
        from jmoraIs.tenancy.context import current_tenant_context
        from .persistence import AuditDefenseJsonCodec,_package_policy,_validate_reference_state
        _validate_reference_state(value,state)
        tenant=current_tenant_context().tenant_id
        canonical=self._exact_package(value.stream_id,value.version,value.package_id,tenant)
        if canonical!=value:raise AuditDefenseBoundaryRejected("DefensePackage does not match exact canonical persistence")
        integrity=sha256(json.dumps(AuditDefenseJsonCodec().encode(value),sort_keys=True,separators=(",",":")).encode()).hexdigest()
        existing=tuple(r for r in self._references.values() if r.package_id==value.package_id and r.tenant_id==tenant)
        if existing:return existing[0]
        reference=PersistedDefensePackageReference("dpr_"+uuid4().hex,value.stream_id,value.version,value.package_id,current_tenant_context().tenant_id,_package_policy(value),integrity,value.created_at,state)
        self._references[reference.reference_id]=reference;return reference
    def append_linked_reference(self,reference,value):
        from .persistence import _validate_transition
        current=self.get_exact(reference)
        _validate_transition(reference,current,value)
        self.append(value)
        return self.reference_for(value)
    def get_exact(self,reference):
        from jmoraIs.tenancy.context import current_tenant_context
        from .persistence import AuditDefenseJsonCodec,_package_integrity,_package_policy,_validate_reference_state
        if not isinstance(reference,PersistedDefensePackageReference) or self._references.get(reference.reference_id)!=reference:raise AuditDefenseBoundaryRejected("owner-issued persisted DefensePackage reference is required")
        if reference.tenant_id!=current_tenant_context().tenant_id:raise AuditDefenseBoundaryRejected("DefensePackage reference tenant mismatch")
        value=self._exact_package(reference.stream_id,reference.version,reference.package_id,reference.tenant_id)
        if reference.state is None:raise LegacyDefenseReference("LEGACY_MISSING_DEFENSE_REFERENCE_STATE")
        _validate_reference_state(value,reference.state)
        if _package_policy(value)!=reference.policy_version or _package_integrity(AuditDefenseJsonCodec(),value)!=reference.integrity_hash:raise AuditDefenseBoundaryRejected("persisted DefensePackage reference mismatch")
        return value
    def _exact_package(self,stream_id,version,package_id,tenant):
        versions=self._streams.get(stream_id,())
        if not isinstance(version,int) or version<1 or version>len(versions):
            raise AuditDefenseBoundaryRejected("exact referenced DefensePackage is unavailable")
        value=versions[version-1]
        if self._tenants.get(package_id)!=tenant:raise AuditDefenseBoundaryRejected("DefensePackage tenant mismatch")
        if (value.stream_id,value.version,value.package_id)!=(stream_id,version,package_id):
            raise AuditDefenseBoundaryRejected("DefensePackage does not match exact canonical persistence")
        predecessor=versions[version-2] if version>1 else None
        if value.previous_package_id!=(predecessor.package_id if predecessor else None):
            raise AuditDefenseBoundaryRejected("DefensePackage predecessor mismatch")
        if predecessor is not None and (predecessor.stream_id,predecessor.version)!=(stream_id,version-1):
            raise AuditDefenseBoundaryRejected("DefensePackage predecessor mismatch")
        link=value.stage11_document_reference
        _validate_document_reference(link)
        if link is not None and link.tenant_id!=tenant:raise AuditDefenseBoundaryRejected("DefensePackage Stage-11 tenant mismatch")
        return value
    def reference_from_upstream(self,reference):
        from jmoraIs.gateway_input import UpstreamArtifactReference
        from jmoraIs.tenancy.context import current_tenant_context
        if not isinstance(reference,UpstreamArtifactReference) or reference.artifact_type!="AuditDefense" or reference.source_context!="audit_defense":raise AuditDefenseBoundaryRejected("AuditDefense upstream reference is required")
        tenant=current_tenant_context().tenant_id
        values=tuple(x for x in self._references.values() if x.tenant_id==tenant and x.stream_id==reference.artifact_id and x.version==reference.artifact_version and x.policy_version==reference.policy_version and x.integrity_hash==reference.integrity_reference)
        if len(values)!=1:raise AuditDefenseBoundaryRejected("exact persisted DefensePackage reference is unavailable")
        return values[0]

def _validate_document_reference(reference):
    if reference is None:return
    if isinstance(reference,PersistedMedicalDocumentVersionReference):
        from jmoraIs.medical_documents.exact_reference import validate_medical_document_reference
        if not validate_medical_document_reference(reference):raise AuditDefenseBoundaryRejected("malformed owner-issued Stage-11 document reference")
        return
    if not isinstance(reference,MedicalDocumentVersionReference) or reference.version<1 or not all((reference.document_stream_id,reference.document_id,reference.tenant_id,reference.policy_version)) or len(reference.integrity_hash)!=64:raise AuditDefenseBoundaryRejected("malformed Stage-11 document reference")
class InMemoryAuditDefenseEventAdapter:
    def __init__(self):self._items=[]
    def append(self,event):
        if any(x.event_id==event.event_id for x in self._items):raise AuditDefenseVersionConflict("defense audit is append-only")
        self._items.append(event)
    def history(self,stream_id):return tuple(x for x in self._items if x.stream_id==stream_id)
class InMemoryAuditClinicalStateAdapter:
    def __init__(self,items):self._items=items
    def facts(self,state_reference_id):return tuple(self._items.get(state_reference_id,()))
class InMemoryAuditReferenceAdapter:
    def __init__(self,items,key):self._items={getattr(x,key):x for x in items}
    def get(self,identifier):return self._items.get(identifier)
class InMemoryAuditLatestAdapter:
    def __init__(self,value):self.value=value
    def latest(self,subject_reference):return self.value
