from __future__ import annotations
import json
from dataclasses import fields,is_dataclass
from datetime import date,datetime,timezone
from enum import Enum
from sqlalchemy import text
from . import domain
from .domain import PatientContext
from .infrastructure import PatientContextPersistenceError
from .privacy import ClinicalAccessAuditEvent,ClinicalAuditEventType,PurposeOfUse
from .privacy import (AuthorizedClinicalIngestionRecord,DeidentificationStatus,LegalBasisType,
    validate_authorized_ingestion_record)
from jmoraIs.tenancy.context import current_tenant_context
from uuid import uuid4
from .exact_reference import (LegacyMissingPersistedPatientContextReference,
    PatientContextReferenceRejected, PersistedPatientContextReference,
    context_integrity, reference_integrity, validate_reference_integrity)

_TYPES={name:value for name,value in vars(domain).items() if isinstance(value,type) and is_dataclass(value)}
_ENUMS={name:value for name,value in vars(domain).items() if isinstance(value,type) and issubclass(value,Enum)}

class PatientContextJsonCodec:
    schema_version=1
    def encode(self,value):
        if is_dataclass(value): return {"__type__":type(value).__name__,**{item.name:self.encode(getattr(value,item.name)) for item in fields(value)}}
        if isinstance(value,Enum): return {"__enum__":type(value).__name__,"value":value.value}
        if isinstance(value,datetime): return {"__datetime__":value.isoformat()}
        if isinstance(value,date): return {"__date__":value.isoformat()}
        if isinstance(value,tuple): return {"__tuple__":[self.encode(item) for item in value]}
        return value
    def decode(self,value):
        if isinstance(value,list): return tuple(self.decode(item) for item in value)
        if not isinstance(value,dict): return value
        if "__enum__" in value: return _ENUMS[value["__enum__"]](value["value"])
        if "__datetime__" in value: return datetime.fromisoformat(value["__datetime__"])
        if "__date__" in value: return date.fromisoformat(value["__date__"])
        if "__tuple__" in value: return tuple(self.decode(item) for item in value["__tuple__"])
        if "__type__" in value:
            kind=_TYPES.get(value["__type__"])
            if kind is None: raise PatientContextPersistenceError("unknown patient context document type")
            return kind(**{key:self.decode(item) for key,item in value.items() if key!="__type__"})
        return {key:self.decode(item) for key,item in value.items()}

class PostgreSQLPatientContextRepository:
    """Append-only PostgreSQL adapter; Alembic remains schema authority."""
    def __init__(self,engine,codec=None):
        if engine.dialect.name!="postgresql": raise ValueError("patient context persistent adapter requires PostgreSQL")
        self._engine=engine;self._codec=codec or PatientContextJsonCodec()
    def append(self,context:PatientContext)->None:
        with self._engine.begin() as connection:
            self.append_on(connection,context)
    def append_on(self,connection,context):
        connection.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
                           {"key":f"patient_context_versions:{context.patient_identity.patient_id}"})
        latest=connection.execute(text("SELECT context_id,version FROM patient_context_versions WHERE patient_id=:patient ORDER BY version DESC LIMIT 1"),{"patient":context.patient_identity.patient_id}).mappings().first()
        if latest and (context.previous_context_id!=latest["context_id"] or context.version!=latest["version"]+1): raise PatientContextPersistenceError("patient context version chain is invalid")
        if not latest and (context.version!=1 or context.previous_context_id is not None): raise PatientContextPersistenceError("patient context history must begin at version 1")
        connection.execute(text("""INSERT INTO patient_context_versions(context_id,patient_id,version,previous_context_id,effective_at,payload,schema_version)
          VALUES(:context,:patient,:version,:previous,:effective,CAST(:payload AS jsonb),:schema)"""),
          {"context":context.context_id,"patient":context.patient_identity.patient_id,"version":context.version,
           "previous":context.previous_context_id,"effective":context.effective_at,
           "payload":json.dumps(self._codec.encode(context),separators=(",",":"),sort_keys=True),
           "schema":self._codec.schema_version})
    def get(self,context_id):
        with self._engine.connect() as connection: payload=connection.execute(text("SELECT payload FROM patient_context_versions WHERE context_id=:id"),{"id":context_id}).scalar_one_or_none()
        return self._codec.decode(payload) if payload else None
    def latest(self,patient_id):
        history=self.history(patient_id);return history[-1] if history else None
    def history(self,patient_id):
        with self._engine.connect() as connection: payloads=connection.execute(text("SELECT payload FROM patient_context_versions WHERE patient_id=:patient ORDER BY version"),{"patient":patient_id}).scalars().all()
        return tuple(self._codec.decode(payload) for payload in payloads)

class PostgreSQLClinicalAccessAuditRepository:
    """Append-only privacy audit containing metadata only, never clinical payload."""
    def __init__(self,engine):
        if engine.dialect.name!="postgresql": raise ValueError("clinical audit adapter requires PostgreSQL")
        self._engine=engine
    def append(self,event):
        with self._engine.begin() as connection:
            self.append_on(connection,event)
    @staticmethod
    def append_on(connection,event):
        connection.execute(text("""INSERT INTO clinical_data_access_audit
              (event_id,event_type,actor_id,organization_id,pseudonymous_patient_id,purpose,occurred_at,policy_version,outcome,reason_code,metadata_keys)
              VALUES(:event_id,:event_type,:actor_id,:organization_id,:patient,:purpose,:occurred_at,:policy,:outcome,:reason,CAST(:keys AS jsonb))"""),
          {"event_id":event.event_id,"event_type":event.event_type.value,"actor_id":event.actor_id,
           "organization_id":event.organization_id,"patient":event.pseudonymous_patient_id,"purpose":event.purpose.value,
           "occurred_at":event.occurred_at,"policy":event.policy_version,"outcome":event.outcome,
           "reason":event.reason_code,"keys":json.dumps(event.metadata_keys)})
    def history(self,pseudonymous_patient_id=None):
        query="SELECT * FROM clinical_data_access_audit"
        params={}
        if pseudonymous_patient_id is not None: query+=" WHERE pseudonymous_patient_id=:patient";params["patient"]=pseudonymous_patient_id
        query+=" ORDER BY sequence_id"
        with self._engine.connect() as connection: rows=connection.execute(text(query),params).mappings().all()
        return tuple(ClinicalAccessAuditEvent(row["event_id"],ClinicalAuditEventType(row["event_type"]),row["actor_id"],row["organization_id"],
          row["pseudonymous_patient_id"],PurposeOfUse(row["purpose"]),row["occurred_at"],row["policy_version"],row["outcome"],row["reason_code"],tuple(row["metadata_keys"])) for row in rows)


class PostgreSQLAuthorizedClinicalIngestionRepository:
    """Atomic Stage-1 record, PatientContext and success-audit persistence."""
    schema_version=1
    def __init__(self,engine,context_codec=None):
        if engine.dialect.name!="postgresql":raise ValueError("authorized ingestion persistence requires PostgreSQL")
        self._engine=engine;self._contexts=PostgreSQLPatientContextRepository(engine,context_codec)
    def append_atomic(self,context,record,audit_events):
        tenant=current_tenant_context()
        if record.tenant_id!=tenant.tenant_id or record.organization_id!=tenant.organization_id:
            raise PatientContextPersistenceError("authorized ingestion tenant mismatch")
        if not validate_authorized_ingestion_record(record):raise PatientContextPersistenceError("ingestion record integrity is invalid")
        if (record.patient_context_id!=context.context_id or record.patient_context_version!=context.version
                or record.pseudonymous_patient_id!=context.patient_identity.patient_id):
            raise PatientContextPersistenceError("ingestion record context linkage is invalid")
        ingestion_event=next((event for event in audit_events if event.event_id==record.audit_event_reference and event.event_type is ClinicalAuditEventType.INGESTION),None)
        if ingestion_event is None:raise PatientContextPersistenceError("canonical ingestion audit linkage is required")
        with self._engine.begin() as connection:
            self._contexts.append_on(connection,context)
            connection.execute(text("""INSERT INTO authorized_clinical_ingestion_records
              (ingestion_record_id,tenant_id,pseudonymous_patient_id,patient_context_id,patient_context_version,
               source,source_reference_id,actor_reference,organization_id,purpose,legal_basis_reference,
               authorization_decision_reference,correlation_id,issued_at,integrity_hash,payload,schema_version)
              VALUES(:id,:tenant,:patient,:context,:version,:source,:source_ref,:actor,:organization,:purpose,
               :basis,:decision,:correlation,:issued,:integrity,CAST(:payload AS jsonb),:schema)"""),
              {"id":record.ingestion_record_id,"tenant":record.tenant_id,"patient":record.pseudonymous_patient_id,
               "context":record.patient_context_id,"version":record.patient_context_version,"source":record.source,
               "source_ref":record.source_reference_id,"actor":record.actor_reference,"organization":record.organization_id,
               "purpose":record.purpose.value,"basis":record.legal_basis_reference,
               "decision":record.authorization_decision_reference,"correlation":record.correlation_id,
               "issued":record.issued_at,"integrity":record.integrity_hash,
               "payload":json.dumps(self._encode(record),sort_keys=True,separators=(",",":")),"schema":self.schema_version})
            for event in audit_events:PostgreSQLClinicalAccessAuditRepository.append_on(connection,event)
    def get(self,ingestion_record_id):
        current_tenant_context()
        with self._engine.connect() as connection:
            row=connection.execute(text("""SELECT r.* FROM authorized_clinical_ingestion_records r
              JOIN patient_context_versions p ON p.context_id=r.patient_context_id AND p.version=r.patient_context_version
              WHERE r.ingestion_record_id=:id"""),{"id":ingestion_record_id}).mappings().first()
        return self._decode_checked(row)
    def get_by_context(self,context_id,version):
        current_tenant_context()
        with self._engine.connect() as connection:
            row=connection.execute(text("""SELECT r.* FROM authorized_clinical_ingestion_records r
              JOIN patient_context_versions p ON p.context_id=r.patient_context_id AND p.version=r.patient_context_version
              WHERE r.patient_context_id=:id AND r.patient_context_version=:version"""),{"id":context_id,"version":version}).mappings().first()
        return self._decode_checked(row)
    def by_correlation(self,correlation_id):
        current_tenant_context()
        with self._engine.connect() as connection:
            rows=connection.execute(text("""SELECT r.* FROM authorized_clinical_ingestion_records r
              JOIN patient_context_versions p ON p.context_id=r.patient_context_id AND p.version=r.patient_context_version
              WHERE r.correlation_id=:id ORDER BY r.sequence_id"""),{"id":correlation_id}).mappings().all()
        return tuple(self._decode_checked(row) for row in rows)
    @staticmethod
    def _encode(record):
        value=dict(record.__dict__)
        for key in ("purpose","legal_basis_type","deidentification_status"):value[key]=value[key].value
        for key in ("classification_result","detected_identifier_classes","retained_field_names","policy_versions"):value[key]=list(value[key])
        for key in ("recorded_at","issued_at"):value[key]=value[key].isoformat()
        return value
    @staticmethod
    def _decode(payload):
        if payload is None:return None
        value=dict(payload);value["purpose"]=PurposeOfUse(value["purpose"]);value["legal_basis_type"]=LegalBasisType(value["legal_basis_type"])
        value["deidentification_status"]=DeidentificationStatus(value["deidentification_status"])
        for key in ("classification_result","detected_identifier_classes","retained_field_names","policy_versions"):value[key]=tuple(value[key])
        for key in ("recorded_at","issued_at"):value[key]=datetime.fromisoformat(value[key])
        return AuthorizedClinicalIngestionRecord(**value)
    @classmethod
    def _decode_checked(cls,row):
        if row is None:return None
        value=cls._decode(row["payload"])
        if value is not None and not validate_authorized_ingestion_record(value):raise PatientContextPersistenceError("persisted ingestion record integrity is invalid")
        columns={"ingestion_record_id":"ingestion_record_id","tenant_id":"tenant_id",
            "pseudonymous_patient_id":"pseudonymous_patient_id","patient_context_id":"patient_context_id",
            "patient_context_version":"patient_context_version","source":"source","source_reference_id":"source_reference_id",
            "actor_reference":"actor_reference","organization_id":"organization_id","purpose":"purpose",
            "legal_basis_reference":"legal_basis_reference","authorization_decision_reference":"authorization_decision_reference",
            "correlation_id":"correlation_id","issued_at":"issued_at","integrity_hash":"integrity_hash"}
        for column,attribute in columns.items():
            expected=getattr(value,attribute);expected=expected.value if isinstance(expected,Enum) else expected
            if row[column]!=expected:raise PatientContextPersistenceError("ingestion record column/payload integrity mismatch")
        return value


class PostgreSQLPatientContextExactReferenceRepository:
    """Owner-side, metadata-only exact reference boundary for canonical PatientContext."""
    def __init__(self,engine,codec=None,*,clock=None):
        if engine.dialect.name!="postgresql":raise ValueError("PatientContext exact references require PostgreSQL")
        self._engine=engine;self._codec=codec or PatientContextJsonCodec()
        self._clock=clock or (lambda:datetime.now(timezone.utc))

    def reference_for(self,context):
        if not isinstance(context,PatientContext):raise PatientContextReferenceRejected("typed PatientContext is required")
        tenant=current_tenant_context()
        row=self._canonical_row(context.context_id,context.version)
        if row is None:raise LegacyMissingPersistedPatientContextReference("LEGACY_MISSING_PERSISTED_PATIENT_CONTEXT_REFERENCE")
        canonical=self._codec.decode(row["context_payload"])
        ingestion=PostgreSQLAuthorizedClinicalIngestionRepository._decode_checked(row)
        if canonical!=context:raise PatientContextReferenceRejected("PatientContext does not match exact canonical persistence")
        self._validate_linkage(canonical,ingestion,row,tenant.tenant_id)
        content_hash=context_integrity(self._codec,canonical);issued=self._clock()
        unsigned=PersistedPatientContextReference("pcr_"+uuid4().hex,canonical.context_id,
            canonical.version,canonical.patient_identity.patient_id,tenant.tenant_id,
            ingestion.provenance_policy_version,ingestion.ingestion_record_id,content_hash,"0"*64,issued)
        reference=PersistedPatientContextReference(**{**unsigned.__dict__,
            "integrity_hash":reference_integrity(unsigned)})
        with self._engine.begin() as connection:
            connection.execute(text("""INSERT INTO patient_context_persisted_references
              (reference_id,context_id,context_version,pseudonymous_patient_id,tenant_id,policy_version,
               authorized_ingestion_record_id,context_integrity_hash,integrity_hash,issued_at)
              VALUES(:reference,:context,:version,:patient,:tenant,:policy,:ingestion,:context_hash,:hash,:issued)"""),
              {"reference":reference.reference_id,"context":reference.context_id,"version":reference.version,
               "patient":reference.pseudonymous_patient_id,"tenant":reference.tenant_id,
               "policy":reference.policy_version,"ingestion":reference.authorized_ingestion_record_id,
               "context_hash":reference.context_integrity_hash,"hash":reference.integrity_hash,
               "issued":reference.issued_at})
        return reference

    def get_exact(self,reference):
        if not isinstance(reference,PersistedPatientContextReference) or not validate_reference_integrity(reference):
            raise PatientContextReferenceRejected("authentic owner-issued PatientContext reference is required")
        tenant=current_tenant_context()
        if reference.tenant_id!=tenant.tenant_id:raise PatientContextReferenceRejected("PatientContext reference tenant mismatch")
        with self._engine.connect() as connection:
            persisted=connection.execute(text("SELECT * FROM patient_context_persisted_references WHERE reference_id=:id"),
                {"id":reference.reference_id}).mappings().first()
        if persisted is None:raise PatientContextReferenceRejected("persisted PatientContext reference is unavailable")
        actual=(persisted["reference_id"],persisted["context_id"],persisted["context_version"],
            persisted["pseudonymous_patient_id"],persisted["tenant_id"],persisted["policy_version"],
            persisted["authorized_ingestion_record_id"],persisted["context_integrity_hash"],
            persisted["integrity_hash"],persisted["issued_at"])
        expected=(reference.reference_id,reference.context_id,reference.version,
            reference.pseudonymous_patient_id,reference.tenant_id,reference.policy_version,
            reference.authorized_ingestion_record_id,reference.context_integrity_hash,
            reference.integrity_hash,reference.issued_at)
        if actual!=expected:raise PatientContextReferenceRejected("PatientContext reference metadata mismatch")
        row=self._canonical_row(reference.context_id,reference.version)
        if row is None:raise PatientContextReferenceRejected("exact referenced PatientContext is unavailable")
        context=self._codec.decode(row["context_payload"])
        ingestion=PostgreSQLAuthorizedClinicalIngestionRepository._decode_checked(row)
        self._validate_linkage(context,ingestion,row,tenant.tenant_id)
        if ingestion.ingestion_record_id!=reference.authorized_ingestion_record_id:
            raise PatientContextReferenceRejected("PatientContext ingestion linkage mismatch")
        if ingestion.provenance_policy_version!=reference.policy_version:
            raise PatientContextReferenceRejected("PatientContext reference policy mismatch")
        if context_integrity(self._codec,context)!=reference.context_integrity_hash:
            raise PatientContextReferenceRejected("PatientContext canonical integrity mismatch")
        self._validate_predecessor(context)
        return context

    def _canonical_row(self,context_id,version):
        with self._engine.connect() as connection:
            return connection.execute(text("""SELECT r.*,p.payload AS context_payload,p.patient_id AS persisted_patient_id,
              p.version AS persisted_context_version,p.previous_context_id AS persisted_previous_context_id,p.tenant_id AS persisted_context_tenant
              FROM patient_context_versions p JOIN authorized_clinical_ingestion_records r
                ON r.patient_context_id=p.context_id AND r.patient_context_version=p.version AND r.tenant_id=p.tenant_id
              WHERE p.context_id=:context AND p.version=:version"""),
              {"context":context_id,"version":version}).mappings().first()

    @staticmethod
    def _validate_linkage(context,ingestion,row,tenant_id):
        expected=(context.context_id,context.version,context.patient_identity.patient_id,tenant_id)
        actual=(ingestion.patient_context_id,ingestion.patient_context_version,
            ingestion.pseudonymous_patient_id,ingestion.tenant_id)
        columns=(row["patient_context_id"],row["persisted_context_version"],row["persisted_patient_id"],
            row["persisted_context_tenant"])
        if actual!=expected or columns!=expected:
            raise PatientContextReferenceRejected("PatientContext exact identity linkage mismatch")

    def _validate_predecessor(self,context):
        if context.version==1:
            if context.previous_context_id is not None:raise PatientContextReferenceRejected("PatientContext genesis linkage is invalid")
            return
        with self._engine.connect() as connection:
            predecessor=connection.execute(text("""SELECT context_id,patient_id,version FROM patient_context_versions
              WHERE context_id=:context AND patient_id=:patient AND version=:version"""),
              {"context":context.previous_context_id,"patient":context.patient_identity.patient_id,
               "version":context.version-1}).mappings().all()
        if len(predecessor)!=1:raise PatientContextReferenceRejected("PatientContext predecessor continuity is invalid")
