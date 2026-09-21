from __future__ import annotations
import json
from hashlib import sha256
from uuid import uuid4
from dataclasses import fields,is_dataclass
from datetime import datetime
from enum import Enum
from sqlalchemy import text
from jmoraIs.tenancy.context import current_tenant_context
from . import domain
from .domain import *
_TYPES={n:v for n,v in vars(domain).items() if isinstance(v,type) and is_dataclass(v)}
_ENUMS={n:v for n,v in vars(domain).items() if isinstance(v,type) and issubclass(v,Enum)}
from jmoraIs.medical_documents.exact_reference import (
    PersistedGuidelineRecommendationSetReference, PersistedOrthopedicAssessmentSetReference,
)
_TYPES.update({c.__name__:c for c in (PersistedGuidelineRecommendationSetReference,PersistedOrthopedicAssessmentSetReference)})
class AuditDefenseJsonCodec:
    schema_version=2
    def encode(self,v):
        if is_dataclass(v):return {"__type__":type(v).__name__,**{f.name:self.encode(getattr(v,f.name)) for f in fields(v)}}
        if isinstance(v,Enum):return {"__enum__":type(v).__name__,"value":v.value}
        if isinstance(v,datetime):return {"__datetime__":v.isoformat()}
        if isinstance(v,tuple):return {"__tuple__":[self.encode(x) for x in v]}
        return v
    def decode(self,v):
        if isinstance(v,list):return tuple(self.decode(x) for x in v)
        if not isinstance(v,dict):return v
        if "__enum__" in v:return _ENUMS[v["__enum__"]](v["value"])
        if "__datetime__" in v:return datetime.fromisoformat(v["__datetime__"])
        if "__tuple__" in v:return tuple(self.decode(x) for x in v["__tuple__"])
        if "__type__" in v:return _TYPES[v["__type__"]](**{k:self.decode(x) for k,x in v.items() if k!="__type__"})
        return {k:self.decode(x) for k,x in v.items()}
class PostgreSQLAuditDefenseRepository:
    def __init__(self,engine,codec=None):self._engine=engine;self._codec=codec or AuditDefenseJsonCodec()
    def append(self,v):
        from .infrastructure import _validate_document_reference
        _validate_document_reference(v.stage11_document_reference)
        with self._engine.begin() as c:
            c.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),{"key":"audit_defense:"+v.stream_id})
            latest=c.execute(text("SELECT package_id,version,stage11_document_stream_id,stage11_document_id,stage11_document_version,stage11_document_integrity_hash FROM audit_defense_versions WHERE stream_id=:s ORDER BY version DESC LIMIT 1"),{"s":v.stream_id}).mappings().first()
            if latest and (v.previous_package_id!=latest["package_id"] or v.version!=latest["version"]+1):raise AuditDefenseVersionConflict("invalid defense version chain")
            if not latest and (v.version!=1 or v.previous_package_id is not None):raise AuditDefenseVersionConflict("defense history must begin at version 1")
            r=v.stage11_document_reference
            if latest and latest["stage11_document_stream_id"] is not None:
                previous_link=tuple(latest[k] for k in ("stage11_document_stream_id","stage11_document_id","stage11_document_version","stage11_document_integrity_hash"))
                next_link=(r.document_stream_id,r.document_id,r.version,r.integrity_hash) if r else None
                if next_link!=previous_link:raise AuditDefenseBoundaryRejected("Stage-11 linkage cannot be removed or replaced")
            c.execute(text("INSERT INTO audit_defense_versions(package_id,stream_id,version,previous_package_id,defense_id,status,review_status,created_at,stage11_document_stream_id,stage11_document_id,stage11_document_version,stage11_document_integrity_hash,payload,schema_version) VALUES(:id,:s,:v,:p,:defense,:status,:review,:at,:doc_stream,:doc_id,:doc_version,:doc_hash,CAST(:payload AS jsonb),:schema)"),{"id":v.package_id,"s":v.stream_id,"v":v.version,"p":v.previous_package_id,"defense":v.defense.defense_id,"status":v.defense.status.value,"review":v.defense.review_status.value,"at":v.created_at,"doc_stream":r.document_stream_id if r else None,"doc_id":r.document_id if r else None,"doc_version":r.version if r else None,"doc_hash":r.integrity_hash if r else None,"payload":json.dumps(self._codec.encode(v),sort_keys=True,separators=(",",":")),"schema":self._codec.schema_version})
    def history(self,s):
        with self._engine.connect() as c:rows=c.execute(text("SELECT payload,stage11_document_stream_id,stage11_document_id,stage11_document_version,stage11_document_integrity_hash FROM audit_defense_versions WHERE stream_id=:s ORDER BY version"),{"s":s}).mappings().all()
        values=[]
        for row in rows:
            value=self._codec.decode(row["payload"]);reference=value.stage11_document_reference
            columns=(row["stage11_document_stream_id"],row["stage11_document_id"],row["stage11_document_version"],row["stage11_document_integrity_hash"])
            expected=(reference.document_stream_id,reference.document_id,reference.version,reference.integrity_hash) if reference else (None,None,None,None)
            if columns!=expected:raise AuditDefenseBoundaryRejected("Stage-11 document reference integrity mismatch")
            values.append(value)
        return tuple(values)
    def latest(self,s):
        values=self.history(s);return values[-1] if values else None
    def _load_exact_package(self,connection,tenant,stream,version,package):
        row=connection.execute(text("""SELECT * FROM audit_defense_versions
          WHERE tenant_id=:tenant AND stream_id=:stream AND version=:version AND package_id=:package"""),
          {"tenant":tenant,"stream":stream,"version":version,"package":package}).mappings().one_or_none()
        if row is None:raise AuditDefenseBoundaryRejected("exact referenced DefensePackage is unavailable")
        try:
            value=self._codec.decode(row["payload"])
            if not isinstance(value,DefensePackage):raise ValueError("invalid package")
            actual=(row["tenant_id"],row["stream_id"],row["version"],row["package_id"],row["previous_package_id"])
            expected=(tenant,value.stream_id,value.version,value.package_id,value.previous_package_id)
            if actual!=expected or value.version<1:raise ValueError("package identity or predecessor mismatch")
            if (row["defense_id"],row["status"],row["review_status"],row["created_at"])!=(value.defense.defense_id,value.defense.status.value,value.defense.review_status.value,value.created_at):
                raise ValueError("package columns mismatch")
            reference=value.stage11_document_reference
            from .infrastructure import _validate_document_reference
            _validate_document_reference(reference)
            expected_link=(reference.document_stream_id,reference.document_id,reference.version,reference.integrity_hash) if reference else (None,None,None,None)
            if reference is not None and reference.tenant_id!=tenant:raise ValueError("Stage-11 tenant mismatch")
            if (row["stage11_document_stream_id"],row["stage11_document_id"],row["stage11_document_version"],row["stage11_document_integrity_hash"])!=expected_link:
                raise ValueError("Stage-11 linkage mismatch")
            if value.version==1:
                if value.previous_package_id is not None:raise ValueError("invalid initial predecessor")
            else:
                predecessor=connection.execute(text("""SELECT stream_id,version FROM audit_defense_versions
                  WHERE tenant_id=:tenant AND package_id=:package"""),
                  {"tenant":tenant,"package":row["previous_package_id"]}).mappings().one_or_none()
                if predecessor is None or (predecessor["stream_id"],predecessor["version"])!=(value.stream_id,value.version-1):
                    raise ValueError("predecessor mismatch")
        except (ValueError,TypeError,KeyError,AttributeError) as exc:
            raise AuditDefenseBoundaryRejected("exact DefensePackage integrity/linkage mismatch") from exc
        return value
    def reference_for(self,value):
        return self._issue_reference(value,DefenseReferenceState.STAGE11_LINKED)
    def reference_for_pre_link(self,value):
        return self._issue_reference(value,DefenseReferenceState.PRE_LINK)
    def _issue_reference(self,value,state):
        _validate_reference_state(value,state)
        tenant=current_tenant_context().tenant_id
        with self._engine.connect() as c:
            canonical=self._load_exact_package(c,tenant,value.stream_id,value.version,value.package_id)
        if canonical!=value:
            raise AuditDefenseBoundaryRejected("DefensePackage does not match exact canonical persistence")
        policy=_package_policy(canonical);integrity=_package_integrity(self._codec,canonical)
        reference=PersistedDefensePackageReference("dpr_"+uuid4().hex,value.stream_id,value.version,
            value.package_id,tenant,policy,integrity,value.created_at,state)
        with self._engine.begin() as c:
            existing=c.execute(text("SELECT * FROM audit_defense_persisted_references WHERE tenant_id=:tenant AND stream_id=:stream AND package_version=:version AND package_id=:package"),
                {"tenant":tenant,"stream":value.stream_id,"version":value.version,"package":value.package_id}).mappings().one_or_none()
            if existing:
                if existing["reference_state"] is None:raise LegacyDefenseReference("LEGACY_MISSING_DEFENSE_REFERENCE_STATE")
                if (existing["reference_state"],existing["policy_version"],existing["integrity_hash"],existing["issued_at"])!=(state.value,policy,integrity,value.created_at):
                    raise AuditDefenseBoundaryRejected("persisted DefensePackage reference mismatch")
                return PersistedDefensePackageReference(existing["reference_id"],value.stream_id,value.version,value.package_id,tenant,policy,integrity,value.created_at,state)
            c.execute(text("""INSERT INTO audit_defense_persisted_references
              (reference_id,tenant_id,stream_id,package_version,package_id,policy_version,integrity_hash,issued_at,reference_state)
              VALUES(:id,:tenant,:stream,:version,:package,:policy,:integrity,:issued,:state)"""),
              {"id":reference.reference_id,"tenant":tenant,"stream":reference.stream_id,
               "version":reference.version,"package":reference.package_id,"policy":reference.policy_version,
               "integrity":reference.integrity_hash,"issued":reference.issued_at,"state":state.value})
        return reference
    def append_linked_reference(self,reference,value):
        from contextlib import nullcontext
        with self._engine.begin() as connection:
            class BoundEngine:
                def connect(self):return nullcontext(connection)
                def begin(self):return nullcontext(connection)
            repository=PostgreSQLAuditDefenseRepository(BoundEngine(),self._codec)
            canonical=repository.get_exact(reference)
            _validate_transition(reference,canonical,value)
            repository.append(value)
            return repository.reference_for(value)
    def get_exact(self,reference):
        if not isinstance(reference,PersistedDefensePackageReference):
            raise AuditDefenseBoundaryRejected("owner-issued persisted DefensePackage reference is required")
        tenant=current_tenant_context().tenant_id
        if reference.tenant_id!=tenant:raise AuditDefenseBoundaryRejected("DefensePackage reference tenant mismatch")
        with self._engine.connect() as c:
            row=c.execute(text("SELECT * FROM audit_defense_persisted_references WHERE tenant_id=:tenant AND reference_id=:id"),
                {"tenant":tenant,"id":reference.reference_id}).mappings().one_or_none()
        if row is None:raise AuditDefenseBoundaryRejected("persisted DefensePackage reference is unavailable")
        if row["reference_state"] is None or reference.state is None:
            raise LegacyDefenseReference("LEGACY_MISSING_DEFENSE_REFERENCE_STATE")
        if not isinstance(reference.state,DefenseReferenceState) or row["reference_state"]!=reference.state.value:
            raise AuditDefenseBoundaryRejected("DefensePackage reference state mismatch")
        actual=(row["reference_id"],row["stream_id"],row["package_version"],row["package_id"],row["tenant_id"],row["policy_version"],row["integrity_hash"],row["issued_at"])
        expected=(reference.reference_id,reference.stream_id,reference.version,reference.package_id,reference.tenant_id,reference.policy_version,reference.integrity_hash,reference.issued_at)
        if actual!=expected:raise AuditDefenseBoundaryRejected("persisted DefensePackage reference mismatch")
        with self._engine.connect() as c:
            value=self._load_exact_package(c,tenant,row["stream_id"],row["package_version"],row["package_id"])
        _validate_reference_state(value,reference.state)
        if _package_policy(value)!=reference.policy_version:raise AuditDefenseBoundaryRejected("DefensePackage reference policy mismatch")
        if _package_integrity(self._codec,value)!=reference.integrity_hash:raise AuditDefenseBoundaryRejected("DefensePackage reference integrity mismatch")
        return value
    def reference_from_upstream(self,reference):
        from jmoraIs.gateway_input import UpstreamArtifactReference
        if not isinstance(reference,UpstreamArtifactReference) or reference.artifact_type!="AuditDefense" or reference.source_context!="audit_defense":
            raise AuditDefenseBoundaryRejected("AuditDefense upstream reference is required")
        tenant=current_tenant_context().tenant_id
        if reference.tenant_id!=tenant:raise AuditDefenseBoundaryRejected("AuditDefense upstream tenant mismatch")
        with self._engine.connect() as c:
            rows=c.execute(text("""SELECT * FROM audit_defense_persisted_references
              WHERE tenant_id=:tenant AND stream_id=:stream AND package_version=:version
                AND policy_version=:policy AND integrity_hash=:integrity"""),
              {"tenant":tenant,"stream":reference.artifact_id,"version":reference.artifact_version,
               "policy":reference.policy_version,"integrity":reference.integrity_reference}).mappings().all()
        if len(rows)!=1:raise AuditDefenseBoundaryRejected("exact persisted DefensePackage reference is unavailable")
        row=rows[0]
        return PersistedDefensePackageReference(row["reference_id"],row["stream_id"],row["package_version"],
            row["package_id"],row["tenant_id"],row["policy_version"],row["integrity_hash"],row["issued_at"],
            DefenseReferenceState(row["reference_state"]) if row["reference_state"] else None)

def _validate_reference_state(value,state):
    if not isinstance(value,DefensePackage) or not isinstance(state,DefenseReferenceState):
        raise AuditDefenseBoundaryRejected("explicit DefensePackage reference state is required")
    from .infrastructure import _validate_document_reference
    link=value.stage11_document_reference
    _validate_document_reference(link)
    if state is DefenseReferenceState.PRE_LINK:
        if link is not None:raise AuditDefenseBoundaryRejected("PRE_LINK must have no Stage-11 linkage")
    elif not isinstance(link,PersistedMedicalDocumentVersionReference):
        raise AuditDefenseBoundaryRejected("owner-issued Stage-11 document reference is required")

def _validate_transition(reference,current,value):
    if reference.state is not DefenseReferenceState.PRE_LINK:
        raise AuditDefenseBoundaryRejected("only PRE_LINK to STAGE11_LINKED is permitted")
    _validate_reference_state(current,DefenseReferenceState.PRE_LINK)
    _validate_reference_state(value,DefenseReferenceState.STAGE11_LINKED)
    if (value.stream_id,value.version,value.previous_package_id,value.defense)!=(current.stream_id,current.version+1,current.package_id,current.defense):
        raise AuditDefenseBoundaryRejected("invalid exact DefensePackage transition")
    if value.stage11_document_reference.tenant_id!=reference.tenant_id:
        raise AuditDefenseBoundaryRejected("Stage-11 tenant mismatch")

def _package_policy(value):
    policies=";".join(sorted(set(value.defense.explainability.policy_versions)))
    if not policies:raise AuditDefenseBoundaryRejected("audit-defense policy reference is required")
    return policies
def _package_integrity(codec,value):
    return sha256(json.dumps(codec.encode(value),sort_keys=True,separators=(",",":")).encode()).hexdigest()
def _validate_chain(history,stream_id):
    for index,item in enumerate(history,1):
        previous=None if index==1 else history[index-2].package_id
        if item.stream_id!=stream_id or item.version!=index or item.previous_package_id!=previous:
            raise AuditDefenseBoundaryRejected("persisted DefensePackage version chain is invalid")
class PostgreSQLAuditDefenseEventAdapter:
    def __init__(self,engine):self._engine=engine
    def append(self,e):
        with self._engine.begin() as c:c.execute(text("INSERT INTO audit_defense_events(event_id,stream_id,package_id,event_type,occurred_at,actor_id,decision_code,reference_ids,policy_version) VALUES(:id,:s,:p,:type,:at,:actor,:decision,CAST(:refs AS jsonb),:policy)"),{"id":e.event_id,"s":e.stream_id,"p":e.package_id,"type":e.event_type.value,"at":e.occurred_at,"actor":e.actor_id,"decision":e.decision_code,"refs":json.dumps(e.reference_ids),"policy":e.policy_version})
    def history(self,s):
        with self._engine.connect() as c:rows=c.execute(text("SELECT * FROM audit_defense_events WHERE stream_id=:s ORDER BY sequence_id"),{"s":s}).mappings().all()
        return tuple(AuditDefenseEvent(x["event_id"],x["stream_id"],x["package_id"],AuditDefenseEventType(x["event_type"]),x["occurred_at"],x["actor_id"],x["decision_code"],tuple(x["reference_ids"]),x["policy_version"]) for x in rows)
