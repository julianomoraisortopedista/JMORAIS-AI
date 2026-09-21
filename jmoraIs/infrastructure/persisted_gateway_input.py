from __future__ import annotations
import json
from dataclasses import asdict
from sqlalchemy import text
from jmoraIs.gateway_input import (PersistedGatewayInput,PersistedGatewayInputError,
    PersistedGatewayInputRecord,canonical_dto_hash,persisted_gateway_input_integrity_hash,
    persisted_gateway_input_record)
from jmoraIs.secrets.domain import KeyReference,SecretPurpose
from jmoraIs.tenancy.context import current_tenant_context

class PersistedGatewayInputTrustService:
    def __init__(self,repository,attestation_verifier,resolvers):self._repository,self._verifier,self._resolvers=repository,attestation_verifier,dict(resolvers)
    def verify_and_resolve(self,identifier):
        record=self._repository.get(identifier)
        if not isinstance(record,PersistedGatewayInputRecord):raise PersistedGatewayInputError("persisted Gateway input is unavailable")
        if record.audit_defense_linkage_status=="LEGACY_MISSING_PERSISTED_DEFENSE_PACKAGE_REFERENCE":
            raise PersistedGatewayInputError(record.audit_defense_linkage_status)
        resolver=self._resolvers.get(record.upstream_artifact_reference.artifact_type)
        if resolver is None:raise PersistedGatewayInputError("upstream artifact resolver is unavailable")
        dto=resolver.resolve_exact(record if record.upstream_artifact_reference.artifact_type=="AuditDefense" else record.upstream_artifact_reference)
        value=PersistedGatewayInput(dto,record.upstream_artifact_reference,record.dto_hash,record.issued_at,record.attestation,record.attestation_key_reference,record.audit_defense_reference)
        if canonical_dto_hash(dto)!=record.dto_hash:raise PersistedGatewayInputError("persisted Gateway DTO hash mismatch")
        if not self._verifier.verify(value):raise PersistedGatewayInputError("persisted Gateway attestation is invalid")
        return value

class InMemoryPersistedGatewayInputRepository:
    def __init__(self,verifier,*,audit_defense_query=None):self._verifier=verifier;self._items={};self._request_links={};self._invocation_links={};self._audit_defense_query=audit_defense_query
    def persist(self,value):return self.append(value)
    def append(self,value):
        self._validate(value);record=persisted_gateway_input_record(value)
        existing=self._items.get(record.persisted_gateway_input_id)
        if existing is not None:
            if existing!=record:raise PersistedGatewayInputError("persisted Gateway input identity collision")
            return existing
        self._items[record.persisted_gateway_input_id]=record;return record
    def _validate(self,value):
        if not isinstance(value,PersistedGatewayInput) or not self._verifier.verify(value):raise PersistedGatewayInputError("trusted owner-issued PersistedGatewayInput is required")
        if canonical_dto_hash(value.dto)!=value.dto_hash:raise PersistedGatewayInputError("persisted Gateway DTO hash mismatch")
        _complete(value)
        _validate_defense_owner(value,self._audit_defense_query)
    def get(self,identifier):return self._items.get(identifier)
    def get_by_upstream(self,t,i,v):return tuple(x for x in self._items.values() if (x.upstream_artifact_reference.artifact_type,x.upstream_artifact_reference.artifact_id,x.upstream_artifact_reference.artifact_version)==(t,i,v))
    def get_by_request(self,request_id):return self.get(self._request_links.get(request_id))
    def get_by_invocation(self,invocation_id):return self.get(self._invocation_links.get(invocation_id))

class PostgreSQLPersistedGatewayInputRepository:
    schema_version=2
    def __init__(self,engine,verifier):self._engine,self._verifier=engine,verifier
    def persist(self,value):return self.append(value)
    def append(self,value):
        if not isinstance(value,PersistedGatewayInput) or not self._verifier.verify(value):raise PersistedGatewayInputError("trusted owner-issued PersistedGatewayInput is required")
        if canonical_dto_hash(value.dto)!=value.dto_hash:raise PersistedGatewayInputError("persisted Gateway DTO hash mismatch")
        _complete(value);record=persisted_gateway_input_record(value);payload=_encode(record)
        if value.audit_defense_reference is not None:
            from jmoraIs.audit_defense.persistence import PostgreSQLAuditDefenseRepository
            _validate_defense_owner(value,PostgreSQLAuditDefenseRepository(self._engine))
        r=record.upstream_artifact_reference;k=record.attestation_key_reference
        with self._engine.begin() as c:
            existing=c.execute(text("SELECT payload FROM persisted_gateway_inputs WHERE persisted_gateway_input_id=:id"),{"id":record.persisted_gateway_input_id}).scalar_one_or_none()
            if existing is not None:
                decoded=_decode(existing)
                if decoded!=record:raise PersistedGatewayInputError("persisted Gateway input identity collision")
                return decoded
            c.execute(text("""INSERT INTO persisted_gateway_inputs
              (persisted_gateway_input_id,tenant_id,artifact_type,artifact_id,artifact_version,source_context,
               integrity_reference,policy_version,dto_hash,issued_at,attestation,key_provider,key_id,key_version,
               record_integrity_hash,payload,schema_version,audit_defense_reference_id)
              VALUES(:id,:tenant,:type,:artifact,:version,:source,:upstream_integrity,:policy,:dto_hash,:issued,
               :attestation,:provider,:key,:key_version,:record_integrity,CAST(:payload AS jsonb),:schema,:defense_reference)"""),
              {"id":record.persisted_gateway_input_id,"tenant":r.tenant_id,"type":r.artifact_type,"artifact":r.artifact_id,
               "version":r.artifact_version,"source":r.source_context,"upstream_integrity":r.integrity_reference,
               "policy":r.policy_version,"dto_hash":record.dto_hash,"issued":record.issued_at,"attestation":record.attestation,
               "provider":k.provider,"key":k.key_id,"key_version":k.version,"record_integrity":record.integrity_hash,
               "payload":json.dumps(payload,sort_keys=True,separators=(",",":")),"schema":self.schema_version,
               "defense_reference":record.audit_defense_reference.reference_id if record.audit_defense_reference else None})
        return record
    def get(self,identifier):
        current_tenant_context()
        with self._engine.connect() as c:row=c.execute(text("SELECT * FROM persisted_gateway_inputs WHERE persisted_gateway_input_id=:id"),{"id":identifier}).mappings().first()
        return self._checked(row)
    def get_by_upstream(self,t,i,v):
        current_tenant_context()
        with self._engine.connect() as c:rows=c.execute(text("SELECT * FROM persisted_gateway_inputs WHERE artifact_type=:t AND artifact_id=:i AND artifact_version=:v ORDER BY sequence_id"),{"t":t,"i":i,"v":v}).mappings().all()
        return tuple(self._checked(x) for x in rows)
    def get_by_request(self,request_id):return self._linked("request_id",request_id)
    def get_by_invocation(self,invocation_id):return self._linked("invocation_id",invocation_id)
    def _linked(self,column,value):
        current_tenant_context()
        with self._engine.connect() as c:row=c.execute(text(f"SELECT p.* FROM persisted_gateway_inputs p JOIN llm_invocations i ON i.persisted_gateway_input_id=p.persisted_gateway_input_id WHERE i.{column}=:id ORDER BY i.sequence_id DESC LIMIT 1"),{"id":value}).mappings().first()
        return self._checked(row)
    @staticmethod
    def _checked(row):
        if row is None:return None
        record=_decode(row["payload"]);r=record.upstream_artifact_reference;k=record.attestation_key_reference
        expected=(record.persisted_gateway_input_id,r.tenant_id,r.artifact_type,r.artifact_id,r.artifact_version,r.source_context,r.integrity_reference,r.policy_version,record.dto_hash,record.issued_at,record.attestation,k.provider,k.key_id,k.version,record.integrity_hash)
        actual=tuple(row[x] for x in ("persisted_gateway_input_id","tenant_id","artifact_type","artifact_id","artifact_version","source_context","integrity_reference","policy_version","dto_hash","issued_at","attestation","key_provider","key_id","key_version","record_integrity_hash"))
        if actual!=expected or record.integrity_hash!=persisted_gateway_input_integrity_hash(record):raise PersistedGatewayInputError("persisted Gateway input record integrity mismatch")
        defense=record.audit_defense_reference
        if row.get("audit_defense_reference_id")!=(defense.reference_id if defense else None):raise PersistedGatewayInputError("persisted defense reference column mismatch")
        if defense is not None:_validate_defense_link(r,defense)
        if row["schema_version"]>=2 and r.artifact_type=="AuditDefense" and defense is None:
            raise PersistedGatewayInputError("LEGACY_MISSING_PERSISTED_DEFENSE_PACKAGE_REFERENCE")
        return record

def _complete(value):
    r=value.reference;k=value.attestation_key_reference
    if k is None or k.purpose is not SecretPurpose.SIGNING_KEY:raise PersistedGatewayInputError("managed signing-key reference is required")
    if r.artifact_version<1 or not all((r.artifact_type,r.artifact_id,r.tenant_id,r.source_context,r.integrity_reference,r.policy_version,value.dto_hash,value.attestation)):raise PersistedGatewayInputError("persisted Gateway input metadata is incomplete")
    if r.tenant_id!=current_tenant_context().tenant_id:raise PersistedGatewayInputError("persisted Gateway input tenant mismatch")
    if value.resolved_at.tzinfo is None or len(value.dto_hash)!=64 or len(value.attestation)!=64:raise PersistedGatewayInputError("persisted Gateway input cryptographic metadata is invalid")
    if r.artifact_type=="AuditDefense" or value.audit_defense_reference is not None:_validate_defense_link(r,value.audit_defense_reference)

def _validate_defense_link(upstream,reference):
    from jmoraIs.audit_defense.domain import PersistedDefensePackageReference
    if not isinstance(reference,PersistedDefensePackageReference):raise PersistedGatewayInputError("LEGACY_MISSING_PERSISTED_DEFENSE_PACKAGE_REFERENCE")
    if (upstream.artifact_type,upstream.source_context)!=("AuditDefense","audit_defense"):
        raise PersistedGatewayInputError("defense reference artifact type mismatch")
    if (upstream.artifact_id,upstream.artifact_version,upstream.tenant_id,upstream.policy_version,upstream.integrity_reference)!=(reference.stream_id,reference.version,reference.tenant_id,reference.policy_version,reference.integrity_hash):
        raise PersistedGatewayInputError("defense exact reference consistency mismatch")

def _validate_defense_owner(value,owner):
    if value.audit_defense_reference is None:return
    if owner is None:raise PersistedGatewayInputError("Audit Defense exact owner query is required")
    package=owner.get_exact(value.audit_defense_reference)
    if package.package_id!=value.audit_defense_reference.package_id or canonical_dto_hash(package.defense)!=value.dto_hash:
        raise PersistedGatewayInputError("defense exact package identity or DTO mismatch")

def _encode(record):
    r=record.upstream_artifact_reference;k=record.attestation_key_reference
    payload={"persisted_gateway_input_id":record.persisted_gateway_input_id,"upstream":asdict(r),"dto_hash":record.dto_hash,"issued_at":record.issued_at.isoformat(),"attestation":record.attestation,"key":{"provider":k.provider,"key_id":k.key_id,"version":k.version,"purpose":k.purpose.value},"integrity_hash":record.integrity_hash}
    if record.audit_defense_reference is not None:
        payload["audit_defense_reference"]=asdict(record.audit_defense_reference)
        payload["audit_defense_reference"]["issued_at"]=record.audit_defense_reference.issued_at.isoformat()
    return payload
def _decode(value):
    from jmoraIs.gateway_input import UpstreamArtifactReference
    from datetime import datetime
    r=value["upstream"];k=value["key"]
    defense=None
    if value.get("audit_defense_reference") is not None:
        from jmoraIs.audit_defense.domain import PersistedDefensePackageReference,DefenseReferenceState
        fields=dict(value["audit_defense_reference"]);fields["issued_at"]=datetime.fromisoformat(fields["issued_at"])
        if fields.get("state") is not None:fields["state"]=DefenseReferenceState(fields["state"])
        defense=PersistedDefensePackageReference(**fields)
    return PersistedGatewayInputRecord(value["persisted_gateway_input_id"],UpstreamArtifactReference(**r),value["dto_hash"],datetime.fromisoformat(value["issued_at"]),value["attestation"],KeyReference(k["provider"],k["key_id"],k["version"],SecretPurpose(k["purpose"])),value["integrity_hash"],defense)
