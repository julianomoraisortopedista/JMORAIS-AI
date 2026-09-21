from datetime import timedelta
import hashlib
import os
from uuid import uuid4

import pytest
from alembic import command as alembic_command
from alembic.config import Config
from sqlalchemy import create_engine, text

from jmoraIs.fhir import (FhirImportCommand, FhirIngestionService,
    FhirR4BundleParser, FhirR4PatientContextMapper, PostgreSQLFhirIdempotencyQueryAdapter)
from jmoraIs.fhir.domain import FhirCodeDecision, FhirDisposition
from jmoraIs.infrastructure.tenant_database import create_tenant_runtime_engine
from jmoraIs.patient_context.domain import RetentionMetadata
from jmoraIs.patient_context.infrastructure import (AuthorizationGrant,
    DeterministicDeidentificationAdapter,InMemoryClinicalDataAuthorizationAdapter,
    InMemoryPatientIdentityMappingAdapter,PurposeBasedDataMinimizationAdapter)
from jmoraIs.patient_context.ingestion import ClinicalIngestionService
from jmoraIs.patient_context.persistence import (PostgreSQLAuthorizedClinicalIngestionRepository,
    PostgreSQLClinicalAccessAuditRepository,PostgreSQLPatientContextExactReferenceRepository,
    PostgreSQLPatientContextRepository)
from jmoraIs.patient_context.privacy import (ActorContext,AuthorizationRequest,ClinicalDataClass,
    IdentityMapping,LegalBasis,LegalBasisType,PurposeOfUse)
from jmoraIs.tenancy.context import TenantContextBinder
from jmoraIs.tenancy.domain import TenantContext
from tests.test_fhir_mvp import NOW, all_entries, bundle, resource


pytestmark=pytest.mark.integration


class Terminology:
    def validate(self,system,code,display):return FhirCodeDecision(True,False,display or code,("canonical-test",))


def migrated():
    url=os.getenv("JMORAIS_TEST_POSTGRES_URL")
    if not url:pytest.skip("JMORAIS_TEST_POSTGRES_URL is required")
    config=Config("alembic.ini");config.set_main_option("sqlalchemy.url",url);alembic_command.upgrade(config,"head")
    return url,create_engine(url,future=True)


def composition(engine,tenant,patient_id,identity_reference):
    contexts=PostgreSQLPatientContextRepository(engine);audit=PostgreSQLClinicalAccessAuditRepository(engine)
    records=PostgreSQLAuthorizedClinicalIngestionRepository(engine)
    actor=ActorContext(tenant.principal_id,"CLINICIAN",tenant.organization_id)
    classes=(ClinicalDataClass.CLINICAL_SENSITIVE,ClinicalDataClass.DIRECT_IDENTIFIER)
    grant=AuthorizationGrant(actor.actor_id,actor.role,actor.organization_id,patient_id,
        (PurposeOfUse.CLINICAL_DOCUMENTATION,),classes,"privacy-v1")
    authorization=InMemoryClinicalDataAuthorizationAdapter((grant,),clock=lambda:NOW)
    identities=InMemoryPatientIdentityMappingAdapter()
    identity=IdentityMapping(identity_reference,patient_id,NOW,"privacy-v1");identities.store(identity)
    clinical=ClinicalIngestionService(contexts,authorization,identities,DeterministicDeidentificationAdapter(),
        PurposeBasedDataMinimizationAdapter({PurposeOfUse.CLINICAL_DOCUMENTATION:(ClinicalDataClass.CLINICAL_SENSITIVE,)}),
        audit,records,allowed_sources=("FHIR_R4",),clock=lambda:NOW)
    exact=PostgreSQLPatientContextExactReferenceRepository(engine,clock=lambda:NOW)
    fhir=FhirIngestionService(FhirR4BundleParser(),FhirR4PatientContextMapper(Terminology()),clinical,
        contexts,exact,PostgreSQLFhirIdempotencyQueryAdapter(engine))
    return fhir,contexts,exact,actor,identity


def command(payload,tenant,patient_id,actor,identity,previous=None):
    classes=(ClinicalDataClass.CLINICAL_SENSITIVE,ClinicalDataClass.DIRECT_IDENTIFIER)
    authorization=AuthorizationRequest(actor,patient_id,PurposeOfUse.CLINICAL_DOCUMENTATION,classes,NOW,"privacy-v1")
    legal=LegalBasis("basis-fhir",LegalBasisType.HEALTHCARE_PROVISION,patient_id,
        (PurposeOfUse.CLINICAL_DOCUMENTATION,),NOW-timedelta(days=1),NOW+timedelta(days=1),"institutional","privacy-v1")
    return FhirImportCommand(payload,identity,actor,PurposeOfUse.CLINICAL_DOCUMENTATION,
        authorization,legal,NOW,RetentionMetadata("clinical-7y",NOW,NOW+timedelta(days=365)),
        previous_context_reference=previous)


def test_fhir_patient_context_handoff_incremental_restart_idempotency_and_rls():
    url,owner=migrated();suffix=uuid4().hex
    tenant=TenantContext("fhir-"+suffix,"fhir-org-"+suffix,"fhir-principal-"+suffix,
        "CLINICIAN","CLINICAL_DOCUMENTATION","privacy-v1","corr-fhir-"+suffix)
    patient_id="pt_"+hashlib.sha256(suffix.encode()).hexdigest();identity_reference="fhir:urn:mrn|MRN-123"
    with owner.begin() as connection:
        connection.execute(text("INSERT INTO tenants(tenant_id,organization_id,display_name,status,policy_version,created_at) VALUES(:t,:o,'FHIR','ACTIVE','privacy-v1',:at)"),{"t":tenant.tenant_id,"o":tenant.organization_id,"at":NOW})
    binder=TenantContextBinder();writer=create_tenant_runtime_engine(url,runtime_role="jmorais_application_writer")
    with binder.bind_tenant(tenant):
        fhir,contexts,exact,actor,identity=composition(writer,tenant,patient_id,identity_reference)
        first=fhir.import_bundle(command(bundle(),tenant,patient_id,actor,identity))
        assert first.disposition is FhirDisposition.INGESTED
        v1=exact.get_exact(first.patient_context_reference)
        v1_reference=first.patient_context_reference
    del fhir,contexts,exact,actor,identity,first,v1
    writer.dispose()

    reader=create_tenant_runtime_engine(url,runtime_role="jmorais_application_reader")
    with binder.bind_tenant(tenant):
        reread_v1=PostgreSQLPatientContextExactReferenceRepository(reader).get_exact(v1_reference)
        assert reread_v1.version==1 and reread_v1.patient_identity.patient_id==patient_id
        source=FhirR4PatientContextMapper(Terminology())._source(FhirR4BundleParser().parse(bundle(),fhir_version="4.0.1"),None)
        assert PostgreSQLFhirIdempotencyQueryAdapter(reader).find(source)==v1_reference
    reader.dispose();del reread_v1

    writer=create_tenant_runtime_engine(url,runtime_role="jmorais_application_writer")
    with binder.bind_tenant(tenant):
        fhir,contexts,exact,actor,identity=composition(writer,tenant,patient_id,identity_reference)
        redelivery=fhir.import_bundle(command(bundle(),tenant,patient_id,actor,identity))
        assert redelivery.disposition is FhirDisposition.IDEMPOTENT_REDELIVERY and redelivery.patient_context_reference==v1_reference
        update_entries=all_entries(extra=(resource("Observation","obs2",subject={"reference":"Patient/p1"},code={"text":"ESR"},valueQuantity={"value":8,"unit":"mm/h"}),))
        second=fhir.import_bundle(command(bundle(update_entries,identifier="bundle-2"),tenant,patient_id,actor,identity,v1_reference))
        assert second.disposition is FhirDisposition.INGESTED
        v2_reference=second.patient_context_reference
        assert exact.get_exact(v2_reference).version==2
    del fhir,contexts,exact,actor,identity,redelivery,second
    writer.dispose()

    reader=create_tenant_runtime_engine(url,runtime_role="jmorais_application_reader")
    with binder.bind_tenant(tenant):
        v2=PostgreSQLPatientContextExactReferenceRepository(reader).get_exact(v2_reference)
        assert v2.version==2 and v2.previous_context_id==v1_reference.context_id
        assert len(v2.laboratory_results)==2
    other=TenantContext("other-"+suffix,"other-org-"+suffix,"other-principal","CLINICIAN",
        "CLINICAL_DOCUMENTATION","privacy-v1","other-corr-"+suffix)
    with owner.begin() as connection:
        connection.execute(text("INSERT INTO tenants(tenant_id,organization_id,display_name,status,policy_version,created_at) VALUES(:t,:o,'Other','ACTIVE','privacy-v1',:at)"),{"t":other.tenant_id,"o":other.organization_id,"at":NOW})
    with binder.bind_tenant(other):
        assert PostgreSQLFhirIdempotencyQueryAdapter(reader).find(source) is None
        with pytest.raises(Exception):PostgreSQLPatientContextExactReferenceRepository(reader).get_exact(v2_reference)
    reader.dispose();owner.dispose()
