import hashlib
import os
from datetime import timedelta
from uuid import uuid4

import pytest
from alembic import command as alembic_command
from alembic.config import Config
from sqlalchemy import create_engine,text
from sqlalchemy.exc import DBAPIError

from jmoraIs.infrastructure.tenant_database import create_tenant_runtime_engine
from jmoraIs.patient_context import *
from jmoraIs.patient_context.infrastructure import (AuthorizationGrant,
    DeterministicDeidentificationAdapter,InMemoryClinicalDataAuthorizationAdapter,
    InMemoryPatientIdentityMappingAdapter,PatientContextPersistenceError,PurposeBasedDataMinimizationAdapter)
from jmoraIs.patient_context.ingestion import ClinicalIngestionCommand,ClinicalIngestionService
from jmoraIs.patient_context.persistence import (PostgreSQLAuthorizedClinicalIngestionRepository,
    PostgreSQLClinicalAccessAuditRepository,PostgreSQLPatientContextRepository)
from jmoraIs.patient_context.privacy import (ActorContext,AuthorizationRequest,ClassifiedClinicalField,
    ClinicalDataClass,DataClassification,DeidentificationStatus,IdentityMapping,IngestionProvenance,
    LegalBasis,LegalBasisType,PurposeOfUse,SensitivityLevel,validate_authorized_ingestion_record)
from jmoraIs.tenancy.context import TenantContextBinder
from jmoraIs.tenancy.domain import MissingTenantContext,TenantContext
from tests.test_patient_context_domain import NOW,context
from evaluation.e2e_acceptance.adapters import AuthorizedIngestionPersistenceAdapter,PatientContextRereadStageAdapter

pytestmark=pytest.mark.integration
SENSITIVE=DataClassification(ClinicalDataClass.CLINICAL_SENSITIVE,SensitivityLevel.HIGH)


def compose_service(engine,patient_id,tenant):
    contexts=PostgreSQLPatientContextRepository(engine);audit=PostgreSQLClinicalAccessAuditRepository(engine)
    records=PostgreSQLAuthorizedClinicalIngestionRepository(engine)
    actor=ActorContext(tenant.principal_id,"CLINICIAN",tenant.organization_id)
    grant=AuthorizationGrant(actor.actor_id,actor.role,actor.organization_id,patient_id,
        (PurposeOfUse.CLINICAL_DOCUMENTATION,),(ClinicalDataClass.CLINICAL_SENSITIVE,),"privacy-v1")
    authorization=InMemoryClinicalDataAuthorizationAdapter((grant,),clock=lambda:NOW)
    identities=InMemoryPatientIdentityMappingAdapter();identities.store(IdentityMapping("ehr:synthetic",patient_id,NOW,"privacy-v1"))
    service=ClinicalIngestionService(contexts,authorization,identities,DeterministicDeidentificationAdapter(),
        PurposeBasedDataMinimizationAdapter({PurposeOfUse.CLINICAL_DOCUMENTATION:(ClinicalDataClass.CLINICAL_SENSITIVE,)}),
        audit,records,allowed_sources=("trusted-ehr",),clock=lambda:NOW)
    return service,contexts,records,audit,actor


def ingestion_command(patient_id,actor,suffix):
    ctx=context("authorized-context-"+suffix,patient_id=patient_id)
    request=AuthorizationRequest(actor,patient_id,PurposeOfUse.CLINICAL_DOCUMENTATION,
        (ClinicalDataClass.CLINICAL_SENSITIVE,),NOW,"privacy-v1")
    basis=LegalBasis("basis-"+suffix,LegalBasisType.HEALTHCARE_PROVISION,patient_id,
        (PurposeOfUse.CLINICAL_DOCUMENTATION,),NOW-timedelta(days=1),NOW+timedelta(days=1),"synthetic-consent","privacy-v1")
    provenance=IngestionProvenance("trusted-ehr","synthetic-author",NOW,NOW,
        DeidentificationStatus.NOT_REQUIRED,"privacy-v1","source-"+suffix)
    return ClinicalIngestionCommand(ctx,"ehr:synthetic",actor,"trusted-ehr",NOW,
        PurposeOfUse.CLINICAL_DOCUMENTATION,request,basis,
        (ClassifiedClinicalField("age_years","45",SENSITIVE),),provenance,1)


def test_atomic_restart_rls_append_only_and_stage1_stage2_handoff():
    url=os.getenv("JMORAIS_TEST_POSTGRES_URL")
    if not url:pytest.skip("JMORAIS_TEST_POSTGRES_URL is required")
    config=Config("alembic.ini");config.set_main_option("sqlalchemy.url",url);alembic_command.upgrade(config,"head")
    owner=create_engine(url,future=True);suffix=uuid4().hex
    tenant=TenantContext("ingestion-"+suffix,"ingestion-org-"+suffix,"ingestion-principal-"+suffix,
        "CLINICIAN","CLINICAL_DOCUMENTATION","privacy-v1","corr-ingestion-"+suffix)
    patient_id="pt_"+hashlib.sha256(suffix.encode()).hexdigest()
    with owner.begin() as connection:
        connection.execute(text("INSERT INTO tenants(tenant_id,organization_id,display_name,status,policy_version,created_at) VALUES(:t,:o,'Ingestion test','ACTIVE','privacy-v1',:at)"),{"t":tenant.tenant_id,"o":tenant.organization_id,"at":NOW})
    writer=create_tenant_runtime_engine(url,runtime_role="jmorais_application_writer")
    reader=create_tenant_runtime_engine(url,runtime_role="jmorais_application_reader")
    binder=TenantContextBinder()
    with binder.bind_tenant(tenant):
        service,contexts,records,audit,actor=compose_service(writer,patient_id,tenant)
        stage1_adapter=AuthorizedIngestionPersistenceAdapter(service,records,ingestion_command(patient_id,actor,suffix))
        receipt=stage1_adapter.execute(None,None);stage1_adapter.persist(receipt);stage1=stage1_adapter.describe(receipt)
        stage1_adapter.release();record=stage1_adapter.reread(stage1.reference_id,stage1.version)
        stage2_adapter=PatientContextRereadStageAdapter(records,contexts)
        stage2_value=stage2_adapter.execute(None,stage1);stage2_adapter.persist(stage2_value);stage2=stage2_adapter.describe(stage2_value)
        stage2_adapter.release();stage2_value=stage2_adapter.reread(stage2.reference_id,stage2.version)
        assert stage1.reference_id!=stage2.reference_id
        assert record.patient_context_id==stage2_value.context_id and record.patient_context_version==stage2_value.version
        record_id,context_id,context_version=record.ingestion_record_id,record.patient_context_id,record.patient_context_version
    del receipt,record,stage1,stage2,stage2_value,service,contexts,records,audit,actor,stage1_adapter,stage2_adapter
    writer.dispose();reader.dispose()

    restarted_reader=create_tenant_runtime_engine(url,runtime_role="jmorais_application_reader")
    with binder.bind_tenant(tenant):
        restarted_records=PostgreSQLAuthorizedClinicalIngestionRepository(restarted_reader)
        reread=restarted_records.get(record_id)
        reread_context=PostgreSQLPatientContextRepository(restarted_reader).get(context_id)
        assert reread==restarted_records.get_by_context(context_id,context_version)
        assert reread_context.context_id==reread.patient_context_id and reread_context.version==reread.patient_context_version
        assert validate_authorized_ingestion_record(reread)
        assert reread.tenant_id==tenant.tenant_id and reread.correlation_id==tenant.correlation_id
    other=TenantContext("other-"+suffix,"other-org-"+suffix,"other-principal","CLINICIAN",
        "CLINICAL_DOCUMENTATION","privacy-v1","other-corr-"+suffix)
    with owner.begin() as connection:
        connection.execute(text("INSERT INTO tenants(tenant_id,organization_id,display_name,status,policy_version,created_at) VALUES(:t,:o,'Other','ACTIVE','privacy-v1',:at)"),{"t":other.tenant_id,"o":other.organization_id,"at":NOW})
    with binder.bind_tenant(other):
        assert PostgreSQLAuthorizedClinicalIngestionRepository(restarted_reader).get(record_id) is None
        assert PostgreSQLPatientContextRepository(restarted_reader).get(context_id) is None
    with pytest.raises(MissingTenantContext):PostgreSQLAuthorizedClinicalIngestionRepository(restarted_reader).get(record_id)
    with pytest.raises(DBAPIError),owner.begin() as connection:
        connection.execute(text("UPDATE authorized_clinical_ingestion_records SET source='tampered' WHERE ingestion_record_id=:id"),{"id":record_id})
    with pytest.raises(DBAPIError),owner.begin() as connection:
        connection.execute(text("DELETE FROM authorized_clinical_ingestion_records WHERE ingestion_record_id=:id"),{"id":record_id})
    with owner.connect() as connection:
        roles=dict(connection.execute(text("SELECT rolname,rolbypassrls FROM pg_roles WHERE rolname IN ('jmorais_application_writer','jmorais_application_reader')")).all())
    assert roles=={"jmorais_application_reader":False,"jmorais_application_writer":False}
    with owner.begin() as connection:
        connection.execute(text("ALTER TABLE authorized_clinical_ingestion_records DISABLE TRIGGER ALL"))
        connection.execute(text("UPDATE authorized_clinical_ingestion_records SET payload=jsonb_set(payload,'{source}','\"tampered\"'::jsonb) WHERE ingestion_record_id=:id"),{"id":record_id})
        connection.execute(text("ALTER TABLE authorized_clinical_ingestion_records ENABLE TRIGGER ALL"))
    with binder.bind_tenant(tenant),pytest.raises(PatientContextPersistenceError,match="integrity"):
        PostgreSQLAuthorizedClinicalIngestionRepository(restarted_reader).get(record_id)
    restarted_reader.dispose();owner.dispose()


def test_ingestion_record_failure_rolls_back_patient_context_and_success_audit():
    url=os.getenv("JMORAIS_TEST_POSTGRES_URL")
    if not url:pytest.skip("JMORAIS_TEST_POSTGRES_URL is required")
    suffix=uuid4().hex;owner=create_engine(url,future=True)
    tenant=TenantContext("rollback-"+suffix,"rollback-org-"+suffix,"rollback-principal","CLINICIAN",
        "CLINICAL_DOCUMENTATION","privacy-v1","rollback-corr-"+suffix)
    with owner.begin() as connection:
        connection.execute(text("INSERT INTO tenants(tenant_id,organization_id,display_name,status,policy_version,created_at) VALUES(:t,:o,'Rollback','ACTIVE','privacy-v1',:at)"),{"t":tenant.tenant_id,"o":tenant.organization_id,"at":NOW})
    patient_id="pt_"+hashlib.sha256(suffix.encode()).hexdigest();writer=create_tenant_runtime_engine(url,runtime_role="jmorais_application_writer")
    with TenantContextBinder().bind_tenant(tenant):
        service,contexts,records,audit,actor=compose_service(writer,patient_id,tenant)
        records._encode=lambda _: {"not_json_serializable":object()}
        with pytest.raises(TypeError):service.ingest(ingestion_command(patient_id,actor,suffix))
        assert contexts.latest(patient_id) is None and audit.history(patient_id)==()
    writer.dispose();owner.dispose()
