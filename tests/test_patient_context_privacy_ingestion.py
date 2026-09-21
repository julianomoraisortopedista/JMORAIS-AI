from dataclasses import FrozenInstanceError, replace
from datetime import timedelta
import pytest

from jmoraIs.patient_context.application import DirectPatientContextWriteProhibited, PatientContextService
from jmoraIs.patient_context.domain import *
from jmoraIs.patient_context.ingestion import *
from jmoraIs.patient_context.infrastructure import *
from jmoraIs.patient_context.privacy import *
from tests.test_patient_context_domain import NOW, PATIENT_ID, context
from jmoraIs.infrastructure.managed_secrets import (
    EphemeralSecretProvider, InMemoryKeyMetadataRepository, InMemorySecretSecurityAudit,
    ManagedHmacPseudonymizationKeyAdapter,
)
from jmoraIs.secrets.domain import KeyReference, KeyState, ManagedKeyMetadata, SecretPurpose, SecretReference
from jmoraIs.tenancy.context import TenantContextBinder
from jmoraIs.tenancy.domain import TenantContext

SENSITIVE=DataClassification(ClinicalDataClass.CLINICAL_SENSITIVE,SensitivityLevel.HIGH)
DIRECT=DataClassification(ClinicalDataClass.DIRECT_IDENTIFIER,SensitivityLevel.RESTRICTED)

@pytest.fixture(autouse=True)
def tenant_context():
    context=TenantContext("tenant-privacy","org-1","actor-1","CLINICIAN","CLINICAL_DOCUMENTATION","privacy-v1","corr-privacy")
    with TenantContextBinder().bind_tenant(context):yield context

def setup(*,authorized=True,allowed=None):
    repository=InMemoryPatientContextRepository();audit=InMemoryClinicalAccessAuditRepository()
    actor=ActorContext("actor-1","CLINICIAN","org-1")
    classes=(ClinicalDataClass.CLINICAL_SENSITIVE,ClinicalDataClass.DIRECT_IDENTIFIER)
    grant=AuthorizationGrant(actor.actor_id,actor.role,actor.organization_id,PATIENT_ID,
        (PurposeOfUse.CLINICAL_DOCUMENTATION,),classes,"privacy-v1")
    auth=InMemoryClinicalDataAuthorizationAdapter((grant,) if authorized else (),clock=lambda:NOW)
    identities=InMemoryPatientIdentityMappingAdapter()
    mapping=IdentityMapping("ehr:123",PATIENT_ID,NOW,"privacy-v1");identities.store(mapping)
    minimizer=PurposeBasedDataMinimizationAdapter(allowed or {PurposeOfUse.CLINICAL_DOCUMENTATION:(ClinicalDataClass.CLINICAL_SENSITIVE,)})
    records=InMemoryAuthorizedClinicalIngestionRepository(repository,audit)
    service=ClinicalIngestionService(repository,auth,identities,DeterministicDeidentificationAdapter(),minimizer,audit,records,
        allowed_sources=("trusted-ehr",),clock=lambda:NOW)
    return service,repository,audit,actor

def command(actor,*,ctx=None,purpose=PurposeOfUse.CLINICAL_DOCUMENTATION,fields=None,source="trusted-ehr",provenance=None):
    ctx=ctx or context();fields=fields if fields is not None else (ClassifiedClinicalField("pain_score","5",SENSITIVE),)
    request=AuthorizationRequest(actor,PATIENT_ID,purpose,
        tuple(dict.fromkeys(item.classification.data_class for item in fields)) or (ClinicalDataClass.CLINICAL_SENSITIVE,),NOW,"privacy-v1")
    basis=LegalBasis("basis-1",LegalBasisType.HEALTHCARE_PROVISION,PATIENT_ID,
        (PurposeOfUse.CLINICAL_DOCUMENTATION,),NOW-timedelta(days=1),NOW+timedelta(days=1),"consent-record","privacy-v1")
    prov=provenance or IngestionProvenance(source,"ehr-system",NOW,NOW,DeidentificationStatus.NOT_REQUIRED,"privacy-v1","doc-1")
    return ClinicalIngestionCommand(ctx,"ehr:123",actor,source,NOW,purpose,request,basis,fields,prov,1)

def test_pseudonymization_is_stable_non_reversible_and_identity_is_separate():
    reference=KeyReference("memory","pseudonymization","v1",SecretPurpose.PSEUDONYMIZATION_HMAC)
    secret=SecretReference("memory","pseudonymization",SecretPurpose.PSEUDONYMIZATION_HMAC,"v1")
    provider=EphemeralSecretProvider({("pseudonymization","v1"):(secret,b"x"*32)})
    metadata=InMemoryKeyMetadataRepository((ManagedKeyMetadata(reference,KeyState.ACTIVE,NOW,NOW,None,None,"privacy-v1"),))
    adapter=HmacPseudonymizationAdapter(ManagedHmacPseudonymizationKeyAdapter(
        provider,metadata,InMemorySecretSecurityAudit()),reference)
    value=adapter.pseudonymize("national-id:123")
    assert value==adapter.pseudonymize("national-id:123") and value.startswith("pt_")
    assert "123" not in value
    assert not hasattr(context().patient_identity,"full_name") and not hasattr(context().patient_identity,"email")

def test_authorized_ingestion_deidentifies_direct_fields_minimizes_and_audits_without_payload():
    service,repository,audit,actor=setup()
    fields=(ClassifiedClinicalField("full_name","Patient Name",DIRECT),ClassifiedClinicalField("age_years","45",SENSITIVE))
    receipt=service.ingest(command(actor,fields=fields))
    assert receipt.deidentification_status==DeidentificationStatus.DEIDENTIFIED.value
    assert receipt.retained_field_names==("age_years",)
    assert repository.latest(PATIENT_ID).retention.policy_id=="clinical-7y"
    assert repository.latest(PATIENT_ID).age_years==45 and repository.latest(PATIENT_ID).weight_kg is None
    events=audit.history(PATIENT_ID)
    assert [event.event_type for event in events]==[ClinicalAuditEventType.IDENTITY_LOOKUP,ClinicalAuditEventType.INGESTION]
    assert "Patient Name" not in repr(events) and "age_years" in events[-1].metadata_keys

def test_unauthorized_actor_and_purpose_mismatch_fail_closed_and_are_audited():
    service,_,audit,actor=setup(authorized=False)
    with pytest.raises(ClinicalAuthorizationDenied): service.ingest(command(actor))
    assert audit.history()[-1].event_type is ClinicalAuditEventType.AUTHORIZATION_DENIAL
    service,_,audit,actor=setup()
    with pytest.raises((ClinicalAuthorizationDenied,PurposeNotAllowed)):
        service.ingest(command(actor,purpose=PurposeOfUse.RESEARCH_PREPARATION))

def test_missing_purpose_unknown_source_and_insufficient_provenance_are_rejected():
    _,_,_,actor=setup()
    with pytest.raises(PurposeNotAllowed): replace(command(actor),purpose=None)
    service,_,_,actor=setup()
    with pytest.raises(InvalidClinicalSource): service.ingest(command(actor,source="unknown"))
    with pytest.raises(InsufficientProvenance): service.ingest(command(actor,provenance=replace(command(actor).provenance,source_reference_id="")))

def test_structured_identifier_is_removed_but_unsafe_free_text_requires_review():
    adapter=DeterministicDeidentificationAdapter()
    result=adapter.transform((ClassifiedClinicalField("email","person@example.org",SENSITIVE),),PATIENT_ID)
    assert result.status is DeidentificationStatus.DEIDENTIFIED and result.fields==()
    service,repository,audit,actor=setup()
    unsafe=(ClassifiedClinicalField("clinical_note","Call person@example.org",SENSITIVE,free_text=True),)
    with pytest.raises(DeidentificationRequired): service.ingest(command(actor,fields=unsafe))
    assert repository.latest(PATIENT_ID) is None
    assert audit.history()[-1].event_type is ClinicalAuditEventType.DEIDENTIFICATION_FAILURE

def test_version_history_survives_canonical_ingestion_and_direct_service_write_is_blocked():
    service,repository,_,actor=setup();first=context();service.ingest(command(actor,ctx=first))
    second=context("context-2",2,first.context_id);service.ingest(command(actor,ctx=second))
    assert tuple(item.context_id for item in repository.history(PATIENT_ID))==(first.context_id,second.context_id)
    with pytest.raises(DirectPatientContextWriteProhibited): PatientContextService(repository).update(second)

def test_privacy_value_objects_are_immutable():
    actor=ActorContext("actor","role","org")
    with pytest.raises(FrozenInstanceError): actor.role="other"

def test_authorized_context_access_is_audited_and_denial_is_fail_closed():
    ingestion,repository,audit,actor=setup();cmd=command(actor);ingestion.ingest(cmd)
    access=AuthorizedPatientContextAccessService(repository,ingestion._authorization,audit,clock=lambda:NOW)
    request=ClinicalContextAccessRequest(actor,PATIENT_ID,cmd.purpose,cmd.authorization,cmd.legal_basis)
    assert access.retrieve(request).patient_identity.patient_id==PATIENT_ID
    assert audit.history()[-1].event_type is ClinicalAuditEventType.CONTEXT_ACCESS
    denied,_,denied_audit,actor=setup(authorized=False)
    access=AuthorizedPatientContextAccessService(repository,denied._authorization,denied_audit,clock=lambda:NOW)
    with pytest.raises(ClinicalAuthorizationDenied): access.retrieve(request)
    assert denied_audit.history()[-1].outcome=="DENIED"
