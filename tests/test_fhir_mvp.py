from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
import json

import pytest

from jmoraIs.fhir import *
from jmoraIs.fhir.domain import (FHIR_RELEASE, FhirCodeDecision, FhirDisposition,
    FhirLimits, FhirReferenceError, FhirSecurityError, FhirStructuralError,
    FhirSemanticError, UnsupportedFhirResource, SUPPORTED_RESOURCES)
from jmoraIs.fhir.infrastructure import CanonicalFhirTerminologyAdapter
from jmoraIs.terminology.domain import MappingConfidence, MappingOutcome, MappedClinicalConcept
from jmoraIs.patient_context.domain import RetentionMetadata
from jmoraIs.patient_context.privacy import IdentityMapping


NOW=datetime(2026,1,1,tzinfo=timezone.utc)
PATIENT_ID="pt_"+"a"*64


class Terminology:
    def __init__(self,accepted=True):self.accepted=accepted
    def validate(self,system,code,display):
        return FhirCodeDecision(self.accepted,not self.accepted,display or code,(f"canonical:{system}:{code}",))


def resource(kind,rid,**values):
    value={"resourceType":kind,"id":rid,"meta":{"versionId":"1","lastUpdated":"2026-01-01T00:00:00Z"},**values}
    return {"fullUrl":f"urn:uuid:{kind.lower()}-{rid}","resource":value}


def all_entries(*,extra=()):
    patient=resource("Patient","p1",identifier=[{"system":"urn:mrn","value":"MRN-123"}],gender="female")
    subject={"reference":"Patient/p1"}
    entries=[patient,resource("Practitioner","pr1"),resource("Organization","o1"),
      resource("Encounter","e1",subject=subject,**{"class":{"code":"AMB"}}),
      resource("Condition","c1",subject=subject,code={"text":"Knee pain"},clinicalStatus={"coding":[{"code":"active"}]}),
      resource("Observation","obs1",subject=subject,code={"text":"CRP"},valueQuantity={"value":3,"unit":"mg/L"}),
      resource("Procedure","proc1",subject=subject,code={"text":"Arthroscopy"}),
      resource("MedicationStatement","med1",subject=subject,status="active",medicationCodeableConcept={"text":"Medication A"}),
      resource("AllergyIntolerance","a1",patient=subject,code={"text":"Latex"}),
      resource("DiagnosticReport","d1",subject=subject,code={"text":"Report"},result=[{"reference":"Observation/obs1"}]),
      resource("DocumentReference","doc1",subject=subject,description="opaque document metadata"),
      resource("ImagingStudy","img1",subject=subject,modality=[{"code":"MR"}]),
      resource("Coverage","cov1",beneficiary=subject),
      resource("CarePlan","cp1",subject=subject,category=[{"text":"Follow-up"}])]
    return entries+list(extra)


def bundle(entries=None,*,identifier="bundle-1",kind="collection"):
    return json.dumps({"resourceType":"Bundle","id":identifier,"type":kind,
        "entry":entries or all_entries()},separators=(",",":" )).encode()


def test_r4_parser_supports_exact_mvp_resources_and_is_immutable():
    parsed=FhirR4BundleParser().parse(bundle(),fhir_version=FHIR_RELEASE)
    assert {item.resource_type for item in parsed.resources}==set(SUPPORTED_RESOURCES)
    assert parsed.fhir_version=="4.0.1" and len(parsed.content_hash)==64
    with pytest.raises(TypeError): parsed.resources[0].data["gender"]="male"
    with pytest.raises(FrozenInstanceError): parsed.bundle_id="changed"


@pytest.mark.parametrize("kind",sorted(SUPPORTED_RESOURCES))
def test_every_supported_resource_requires_structural_identity(kind):
    entries=all_entries()
    target=next(item for item in entries if item["resource"]["resourceType"]==kind)
    target["resource"].pop("id")
    with pytest.raises(FhirStructuralError):FhirR4BundleParser().parse(bundle(entries),fhir_version=FHIR_RELEASE)


@pytest.mark.parametrize("kind",("collection","transaction","batch","document"))
def test_supported_bundle_types_are_local_ingestion_containers_only(kind):
    parsed=FhirR4BundleParser().parse(bundle(kind=kind),fhir_version=FHIR_RELEASE)
    assert parsed.bundle_type==kind


@pytest.mark.parametrize("payload,error",[
    (b"{}",FhirStructuralError),
    (b"not-json",FhirStructuralError),
    (bundle([resource("Questionnaire","q1")]),UnsupportedFhirResource),
])
def test_malformed_and_unsupported_input_fails_closed(payload,error):
    with pytest.raises(error):FhirR4BundleParser().parse(payload,fhir_version=FHIR_RELEASE)
    with pytest.raises(FhirStructuralError):FhirR4BundleParser().parse(bundle(),fhir_version="4.3.0")


def test_reference_resolution_rejects_missing_duplicate_ambiguous_external_and_circular():
    missing=all_entries();missing[4]["resource"]["subject"]={"reference":"Patient/missing"}
    with pytest.raises(FhirReferenceError):FhirR4BundleParser().parse(bundle(missing),fhir_version=FHIR_RELEASE)
    duplicate=all_entries()+[resource("Patient","p1",identifier=[{"system":"x","value":"y"}])]
    with pytest.raises(FhirReferenceError):FhirR4BundleParser().parse(bundle(duplicate),fhir_version=FHIR_RELEASE)
    ambiguous=all_entries();ambiguous[2]["fullUrl"]=ambiguous[1]["fullUrl"]
    with pytest.raises(FhirReferenceError,match="ambiguous"):FhirR4BundleParser().parse(bundle(ambiguous),fhir_version=FHIR_RELEASE)
    external=all_entries();external[4]["resource"]["subject"]={"reference":"https://evil.invalid/Patient/p1"}
    with pytest.raises(FhirSecurityError):FhirR4BundleParser().parse(bundle(external),fhir_version=FHIR_RELEASE)
    circular=all_entries();circular[0]["resource"]["managingOrganization"]={"reference":"Organization/o1"};circular[2]["resource"]["partOf"]={"reference":"Patient/p1"}
    with pytest.raises(FhirReferenceError,match="circular"):FhirR4BundleParser().parse(bundle(circular),fhir_version=FHIR_RELEASE)


def test_limits_reject_oversized_bundle_components_results_and_metadata():
    with pytest.raises(FhirSecurityError):FhirR4BundleParser(FhirLimits(max_bundle_bytes=10)).parse(bundle(),fhir_version=FHIR_RELEASE)
    entries=all_entries();entries[5]["resource"]["component"]=[{}]*51
    with pytest.raises(FhirSecurityError):FhirR4BundleParser().parse(bundle(entries),fhir_version=FHIR_RELEASE)
    entries=all_entries();entries[9]["resource"]["result"]=[{"reference":"Observation/obs1"}]*101
    with pytest.raises(FhirSecurityError):FhirR4BundleParser().parse(bundle(entries),fhir_version=FHIR_RELEASE)
    entries=all_entries();entries[10]["resource"]["description"]="x"*4097
    with pytest.raises(FhirSecurityError):FhirR4BundleParser().parse(bundle(entries),fhir_version=FHIR_RELEASE)


def test_deterministic_mapping_covers_resources_without_direct_identity_or_fabrication():
    parsed=FhirR4BundleParser().parse(bundle(),fhir_version=FHIR_RELEASE)
    mapping=IdentityMapping("fhir:urn:mrn|MRN-123",PATIENT_ID,NOW,"privacy-v1")
    retention=RetentionMetadata("clinical-7y",NOW,NOW)
    result=FhirR4PatientContextMapper(Terminology()).map(parsed,mapping,recorded_at=NOW,retention=retention)
    context=result.context
    assert context.patient_identity.patient_id==PATIENT_ID and "MRN-123" not in repr(context)
    assert (len(context.clinical_problems),len(context.laboratory_results),len(context.procedures),
        len(context.medications),len(context.allergies),len(context.imaging_studies),len(context.encounters),
        len(context.clinical_note_references),len(context.follow_up_plans))==(1,1,1,1,1,1,1,3,1)
    assert {item.name for item in result.clinical_payload}>={"national_id","clinical_problems","sex"}
    assert result==FhirR4PatientContextMapper(Terminology()).map(parsed,mapping,recorded_at=NOW,retention=retention)


def test_unknown_or_ambiguous_terminology_and_conflicts_require_review():
    entries=all_entries();entries[4]["resource"]["code"]={"coding":[{"system":"http://snomed.info/sct","code":"x"}]}
    parsed=FhirR4BundleParser().parse(bundle(entries),fhir_version=FHIR_RELEASE)
    mapping=IdentityMapping("fhir:urn:mrn|MRN-123",PATIENT_ID,NOW,"privacy-v1")
    retention=RetentionMetadata("clinical-7y",NOW,NOW)
    rejected=FhirR4PatientContextMapper(Terminology(False)).map(parsed,mapping,recorded_at=NOW,retention=retention)
    assert rejected.context is None and "TERMINOLOGY_REVIEW_REQUIRED" in "|".join(rejected.review_reasons)
    baseline=FhirR4BundleParser().parse(bundle(),fhir_version=FHIR_RELEASE)
    accepted=FhirR4PatientContextMapper(Terminology()).map(baseline,mapping,recorded_at=NOW,retention=retention)
    changed_entries=all_entries();changed_entries[4]["resource"]["code"]={"text":"Changed knee problem"}
    changed=FhirR4BundleParser().parse(bundle(changed_entries),fhir_version=FHIR_RELEASE)
    conflicting=FhirR4PatientContextMapper(Terminology()).map(changed,mapping,recorded_at=NOW,retention=retention,previous=accepted.context)
    assert conflicting.context is None and "CONFLICTING_UPDATE" in "|".join(conflicting.review_reasons)


def test_source_reference_is_hash_bound_and_raw_payload_is_not_canonical():
    parsed=FhirR4BundleParser().parse(bundle(),fhir_version=FHIR_RELEASE)
    mapping=IdentityMapping("fhir:urn:mrn|MRN-123",PATIENT_ID,NOW,"privacy-v1")
    result=FhirR4PatientContextMapper(Terminology()).map(parsed,mapping,recorded_at=NOW,
        retention=RetentionMetadata("clinical-7y",NOW,NOW))
    assert parsed.content_hash in result.source_reference_id
    assert "MRN-123" not in result.source_reference_id and "entry" not in result.context.provenance


def test_canonical_terminology_adapter_fails_closed_for_unknown_system():
    class Query:
        def resolve(self,term,system,version):
            return MappedClinicalConcept(term,system,version,MappingOutcome.MAPPED,(),None,
                MappingConfidence.HIGH,False,("canonical",))
    adapter=CanonicalFhirTerminologyAdapter(Query(),{})
    decision=adapter.validate("urn:unknown","x",None)
    assert not decision.accepted and decision.review_required
