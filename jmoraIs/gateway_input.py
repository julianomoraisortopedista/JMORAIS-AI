from __future__ import annotations

import hmac
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
from hashlib import sha256
from typing import Protocol, TYPE_CHECKING
if TYPE_CHECKING:
    from jmoraIs.audit_defense.domain import PersistedDefensePackageReference
from jmoraIs.secrets.domain import KeyReference
from jmoraIs.tenancy.context import current_tenant_context

class PersistedGatewayInputError(RuntimeError): pass

@dataclass(frozen=True)
class UpstreamArtifactReference:
    artifact_type: str; artifact_id: str; artifact_version: int; tenant_id: str
    integrity_reference: str; policy_version: str; source_context: str

@dataclass(frozen=True)
class PersistedGatewayInput:
    dto: object; reference: UpstreamArtifactReference; dto_hash: str; resolved_at: datetime; attestation: str
    attestation_key_reference: KeyReference|None=None
    audit_defense_reference: PersistedDefensePackageReference|None=None

@dataclass(frozen=True)
class PersistedGatewayInputRecord:
    persisted_gateway_input_id:str;upstream_artifact_reference:UpstreamArtifactReference;dto_hash:str
    issued_at:datetime;attestation:str;attestation_key_reference:KeyReference;integrity_hash:str
    audit_defense_reference: PersistedDefensePackageReference|None=None

    @property
    def audit_defense_linkage_status(self):
        if self.upstream_artifact_reference.artifact_type != "AuditDefense":return "NOT_APPLICABLE"
        return "EXACT" if self.audit_defense_reference is not None else "LEGACY_MISSING_PERSISTED_DEFENSE_PACKAGE_REFERENCE"

class PersistedGatewayInputQueryPort(Protocol):
    def get(self,persisted_gateway_input_id:str)->PersistedGatewayInputRecord|None:...
    def get_by_upstream(self,artifact_type:str,artifact_id:str,artifact_version:int)->tuple[PersistedGatewayInputRecord,...]:...
    def get_by_request(self,request_id:str)->PersistedGatewayInputRecord|None:...
    def get_by_invocation(self,invocation_id:str)->PersistedGatewayInputRecord|None:...
class PersistedGatewayInputRepository(PersistedGatewayInputQueryPort,Protocol):
    def append(self,value:PersistedGatewayInput)->PersistedGatewayInputRecord:...
class PersistedGatewayInputVerificationPort(Protocol):
    def verify(self,value:PersistedGatewayInput)->bool:...
class PersistedGatewayInputPersistencePort(Protocol):
    def persist(self,value:PersistedGatewayInput)->PersistedGatewayInputRecord:...

class PersistedGatewayInputAttestor(Protocol):
    def issue(self, value: PersistedGatewayInput) -> str: ...
    def verify(self, value: PersistedGatewayInput) -> bool: ...

def canonical_dto_payload(value: object) -> str:
    if not hasattr(value,"__dataclass_fields__"): raise PersistedGatewayInputError("canonical DTO must be an immutable dataclass")
    return json.dumps(asdict(value),sort_keys=True,separators=(",",":"),default=_json_default)

def canonical_dto_hash(value: object) -> str: return sha256(canonical_dto_payload(value).encode()).hexdigest()

class HMACPersistedGatewayInputAttestor:
    def __init__(self,key: bytes):
        if not isinstance(key,bytes) or len(key)<32: raise PersistedGatewayInputError("persisted-input attestation key must contain at least 32 bytes")
        self._key=key
    def issue(self,value: PersistedGatewayInput)->str:return hmac.new(self._key,_attestation_material(value),sha256).hexdigest()
    def verify(self,value: PersistedGatewayInput)->bool:return isinstance(value,PersistedGatewayInput) and bool(value.attestation) and hmac.compare_digest(value.attestation,self.issue(value))

def issue_persisted_gateway_input(dto,reference,resolved_at,attestor,attestation_key_reference=None,*,audit_defense_reference=None):
    if resolved_at.tzinfo is None: raise PersistedGatewayInputError("persisted-input timestamp must be timezone-aware")
    digest=canonical_dto_hash(dto);unsigned=PersistedGatewayInput(dto,reference,digest,resolved_at,"",attestation_key_reference)
    return PersistedGatewayInput(dto,reference,digest,resolved_at,attestor.issue(unsigned),attestation_key_reference,audit_defense_reference)

def persisted_gateway_input_record(value):
    if not isinstance(value,PersistedGatewayInput) or value.attestation_key_reference is None:raise PersistedGatewayInputError("managed attestation key reference is required")
    if value.reference.tenant_id!=current_tenant_context().tenant_id:raise PersistedGatewayInputError("persisted Gateway input tenant mismatch")
    material={"upstream":asdict(value.reference),"dto_hash":value.dto_hash,"issued_at":value.resolved_at.isoformat(),"attestation":value.attestation,"key":asdict(value.attestation_key_reference)}
    if value.audit_defense_reference is not None:material["audit_defense_reference"]=asdict(value.audit_defense_reference)
    integrity=sha256(json.dumps(material,sort_keys=True,separators=(",",":"),default=_json_default).encode()).hexdigest()
    identifier="pgi_"+sha256((integrity+"|"+value.attestation).encode()).hexdigest()
    return PersistedGatewayInputRecord(identifier,value.reference,value.dto_hash,value.resolved_at,value.attestation,value.attestation_key_reference,integrity,value.audit_defense_reference)

def persisted_gateway_input_integrity_hash(record):
    material={"upstream":asdict(record.upstream_artifact_reference),"dto_hash":record.dto_hash,"issued_at":record.issued_at.isoformat(),"attestation":record.attestation,"key":asdict(record.attestation_key_reference)}
    if record.audit_defense_reference is not None:material["audit_defense_reference"]=asdict(record.audit_defense_reference)
    return sha256(json.dumps(material,sort_keys=True,separators=(",",":"),default=_json_default).encode()).hexdigest()

def _attestation_material(value):
    reference=value.reference
    return "|".join((reference.artifact_type,reference.artifact_id,str(reference.artifact_version),reference.tenant_id,reference.integrity_reference,reference.policy_version,reference.source_context,value.dto_hash,value.resolved_at.isoformat())).encode()

def _json_default(value):return value.value if isinstance(value,Enum) else value.isoformat() if isinstance(value,datetime) else str(value)
