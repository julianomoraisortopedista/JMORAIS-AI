from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
import re
from uuid import uuid4
from .domain import PatientContext
from .privacy import *

class PatientContextPersistenceError(RuntimeError): pass

class InMemoryPatientContextRepository:
    def __init__(self): self._items: dict[str,PatientContext]={};self._patients: dict[str,list[str]]={}
    def append(self,context:PatientContext)->None:
        if context.context_id in self._items: raise PatientContextPersistenceError("patient context cannot be overwritten")
        patient_id=context.patient_identity.patient_id;history=self.history(patient_id)
        if history and (context.previous_context_id!=history[-1].context_id or context.version!=history[-1].version+1): raise PatientContextPersistenceError("patient context version chain is invalid")
        if not history and context.version!=1: raise PatientContextPersistenceError("patient context history must begin at version 1")
        self._items[context.context_id]=context;self._patients.setdefault(patient_id,[]).append(context.context_id)
    def get(self,context_id:str)->PatientContext|None:return self._items.get(context_id)
    def latest(self,patient_id:str)->PatientContext|None:
        identifiers=self._patients.get(patient_id,[]);return self._items[identifiers[-1]] if identifiers else None
    def history(self,patient_id:str)->tuple[PatientContext,...]:return tuple(self._items[item] for item in self._patients.get(patient_id,[]))

@dataclass(frozen=True)
class PatientContextDocument:
    """PostgreSQL adapter contract: immutable JSON document plus version-chain columns."""
    context_id:str;patient_id:str;version:int;previous_context_id:str|None;effective_at:datetime;payload:dict

@dataclass(frozen=True)
class AuthorizationGrant:
    actor_id:str;role:str;organization_id:str;patient_scope:str
    purposes:tuple[PurposeOfUse,...];data_classes:tuple[ClinicalDataClass,...];policy_version:str

class InMemoryClinicalDataAuthorizationAdapter:
    def __init__(self, grants=(), *, clock): self._grants=tuple(grants);self._clock=clock
    def authorize(self,request,legal_basis):
        now=self._clock();valid_basis=(legal_basis.valid_from<=now and (legal_basis.valid_until is None or now<=legal_basis.valid_until)
          and request.patient_scope==legal_basis.patient_scope and request.purpose in legal_basis.purposes
          and request.policy_version==legal_basis.policy_version)
        match=next((g for g in self._grants if g.actor_id==request.actor.actor_id and g.role==request.actor.role
          and g.organization_id==request.actor.organization_id and g.patient_scope==request.patient_scope
          and request.purpose in g.purposes and set(request.requested_classes).issubset(set(g.data_classes))
          and g.policy_version==request.policy_version),None)
        allowed=bool(valid_basis and match)
        return AuthorizationDecision(allowed,str(uuid4()),request.policy_version,now,"ALLOWED" if allowed else "POLICY_DENIED")

class HmacPseudonymizationAdapter:
    def __init__(self,key_port,key_reference,*,actor_id="patient-context-ingestion"):
        self._keys,self._reference,self._actor=key_port,key_reference,actor_id
    def pseudonymize(self,identity_reference):
        if not identity_reference.strip(): raise IdentityBoundaryViolation("identity reference is required")
        return self._keys.pseudonymize(self._reference,identity_reference,actor_id=self._actor).pseudonymous_id

class InMemoryPatientIdentityMappingAdapter:
    def __init__(self): self._items={}
    def store(self,mapping):
        existing=self._items.get(mapping.identity_reference)
        if existing and existing!=mapping: raise IdentityBoundaryViolation("identity mapping is immutable")
        self._items[mapping.identity_reference]=mapping
    def resolve(self,identity_reference,authorization):
        if not authorization.allowed: raise ClinicalAuthorizationDenied("identity lookup requires authorization")
        return self._items.get(identity_reference)

class DeterministicDeidentificationAdapter:
    _direct_names=frozenset({"full_name","name","national_id","cpf","email","phone","street_address","address"})
    _patterns=(re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}"),re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b"))
    def transform(self,fields,pseudonymous_patient_id):
        retained=[];detected=[];review=False
        for item in fields:
            if item.free_text: review=True;detected.append(item.name);continue
            direct=item.classification.data_class==ClinicalDataClass.DIRECT_IDENTIFIER or item.name.lower() in self._direct_names
            pattern=any(rx.search(item.value or "") for rx in self._patterns)
            if direct or pattern: detected.append(item.name);continue
            retained.append(item)
        status=DeidentificationStatus.REVIEW_REQUIRED if review else (DeidentificationStatus.DEIDENTIFIED if detected else DeidentificationStatus.NOT_REQUIRED)
        return DeidentificationResult(tuple(retained),status,tuple(detected))

class PurposeBasedDataMinimizationAdapter:
    def __init__(self,allowed): self._allowed={key:frozenset(value) for key,value in allowed.items()}
    def minimize(self,fields,purpose):
        allowed=self._allowed.get(purpose,frozenset())
        return tuple(item for item in fields if item.classification.data_class in allowed)

class InMemoryClinicalAccessAuditRepository:
    def __init__(self): self._events=[];self._ids=set()
    def append(self,event):
        if event.event_id in self._ids: raise PatientContextPersistenceError("audit event is append-only")
        self._ids.add(event.event_id);self._events.append(event)
    def history(self,pseudonymous_patient_id=None):
        return tuple(item for item in self._events if pseudonymous_patient_id is None or item.pseudonymous_patient_id==pseudonymous_patient_id)

class InMemoryAuthorizedClinicalIngestionRepository:
    def __init__(self,contexts,audit):self._contexts=contexts;self._audit=audit;self._records={}
    def append_atomic(self,context,record,audit_events):
        if not validate_authorized_ingestion_record(record):raise PatientContextPersistenceError("ingestion record integrity is invalid")
        if record.ingestion_record_id in self._records or self.get_by_context(record.patient_context_id,record.patient_context_version):
            raise PatientContextPersistenceError("authorized ingestion record is append-only")
        # Validate all identifiers before the in-memory commit section.
        if record.patient_context_id!=context.context_id or record.patient_context_version!=context.version or record.pseudonymous_patient_id!=context.patient_identity.patient_id:
            raise PatientContextPersistenceError("ingestion record context linkage is invalid")
        ingestion_event=next((event for event in audit_events if event.event_id==record.audit_event_reference and event.event_type is ClinicalAuditEventType.INGESTION),None)
        if ingestion_event is None:raise PatientContextPersistenceError("canonical ingestion audit linkage is required")
        if any(event.event_id in self._audit._ids for event in audit_events):raise PatientContextPersistenceError("audit event is append-only")
        self._contexts.append(context)
        self._records[record.ingestion_record_id]=record
        for event in audit_events:self._audit.append(event)
    def get(self,ingestion_record_id):
        value=self._records.get(ingestion_record_id)
        if value and not validate_authorized_ingestion_record(value):raise PatientContextPersistenceError("ingestion record integrity is invalid")
        return value
    def get_by_context(self,context_id,version):
        return next((self.get(item.ingestion_record_id) for item in self._records.values() if item.patient_context_id==context_id and item.patient_context_version==version),None)
    def by_correlation(self,correlation_id):
        return tuple(self.get(item.ingestion_record_id) for item in self._records.values() if item.correlation_id==correlation_id)
