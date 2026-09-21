from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from hashlib import sha256
import json
import re

from jmoraIs.patient_context.domain import (
    Allergy, ClinicalNoteReference, ClinicalProblem, ClinicalTimeline, Encounter,
    EncounterType, FollowUpPlan, ImagingModality, ImagingStudy, LaboratoryResult,
    Medication, MedicationStatus, PatientContext, PatientIdentity, ProcedureHistory,
    RetentionMetadata, Sex,
)
from jmoraIs.patient_context.privacy import (ClassifiedClinicalField, ClinicalDataClass,
    DataClassification, IdentityMapping, SensitivityLevel)

from .domain import FhirMappingResult, FhirSemanticError


_PHI = (re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}"),
        re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b"))


def _stable(prefix, value): return prefix + sha256(value.encode()).hexdigest()[:48]
def _json(resource): return json.dumps(dict(resource.data),sort_keys=True,separators=(",",":"))
def _event_id(resource): return _stable("fhir_",resource.logical_reference+"|"+(resource.version_id or "unversioned"))
def _at(resource, fallback): return resource.last_updated or fallback
def _provenance(resource,bundle,policy):
    return f"FHIR|{bundle.fhir_version}|{resource.logical_reference}|{resource.version_id or 'UNVERSIONED'}|{policy}"


class FhirR4PatientContextMapper:
    def __init__(self, terminology, *, mapping_policy_version="fhir-map-r4-v1"):
        self._terminology=terminology;self._policy=mapping_policy_version

    def map(self,bundle,identity:IdentityMapping,*,recorded_at,retention,previous=None):
        patients=tuple(item for item in bundle.resources if item.resource_type=="Patient")
        if len(patients)!=1: raise FhirSemanticError("Bundle must contain exactly one Patient")
        patient=patients[0];reasons=[];mapped=[]
        sex={"female":Sex.FEMALE,"male":Sex.MALE,"other":Sex.INTERSEX,"unknown":Sex.UNKNOWN}.get(patient.data.get("gender"),Sex.NOT_REPORTED)
        timeline_id=previous.timeline.timeline_id if previous else _stable("timeline_",identity.pseudonymous_patient_id)
        common={"source":"FHIR_R4","author":"fhir-adapter","confidence":0.8,"timeline_id":timeline_id}
        collections={name:list(getattr(previous,name) if previous else ()) for name in (
            "clinical_problems","medications","allergies","procedures","laboratory_results",
            "imaging_studies","encounters","clinical_note_references","follow_up_plans")}
        for resource in bundle.resources:
            if resource.resource_type in {"Patient","Practitioner","Organization"}: mapped.append(resource.logical_reference);continue
            label=(self._label(resource,reasons) if resource.resource_type in
                {"Condition","Observation","Procedure","AllergyIntolerance","CarePlan"} else None)
            event={**common,"entity_id":_event_id(resource),"recorded_at":_at(resource,recorded_at),
                "occurred_at":_at(resource,recorded_at),"provenance":_provenance(resource,bundle,self._policy)}
            value=None;target=None
            if resource.resource_type=="Condition" and label:
                value=ClinicalProblem(**event,name=label,status=self._status(resource,"clinicalStatus") or "UNKNOWN");target="clinical_problems"
            elif resource.resource_type=="Observation" and label:
                quantity=resource.data.get("valueQuantity") or {}
                scalar=quantity.get("value",resource.data.get("valueString"))
                if scalar is None: reasons.append(f"Observation/{resource.resource_id}:MISSING_VALUE")
                else: value=LaboratoryResult(**event,test_name=label,value=str(scalar),unit=quantity.get("unit") or quantity.get("code"));target="laboratory_results"
            elif resource.resource_type=="Procedure" and label:
                value=ProcedureHistory(**event,procedure=label);target="procedures"
            elif resource.resource_type=="MedicationStatement":
                medication=resource.data.get("medicationCodeableConcept") or {}
                label=self._codeable(medication,reasons,resource.logical_reference)
                if label:
                    status={"active":MedicationStatus.ACTIVE,"completed":MedicationStatus.INACTIVE,
                        "stopped":MedicationStatus.INACTIVE}.get(resource.data.get("status"),MedicationStatus.UNKNOWN)
                    value=Medication(**event,name=label,status=status);target="medications"
            elif resource.resource_type=="AllergyIntolerance" and label:
                value=Allergy(**event,substance=label);target="allergies"
            elif resource.resource_type=="Encounter":
                kind={"AMB":EncounterType.CONSULTATION,"EMER":EncounterType.CONSULTATION,
                    "IMP":EncounterType.CONSULTATION}.get(((resource.data.get("class") or {}).get("code")))
                if kind is None: reasons.append(f"{resource.logical_reference}:UNKNOWN_ENCOUNTER_CLASS")
                else: value=Encounter(**event,encounter_type=kind);target="encounters"
            elif resource.resource_type=="DiagnosticReport":
                value=ClinicalNoteReference(**event,note_type="DIAGNOSTIC_REPORT",reference=resource.logical_reference);target="clinical_note_references"
            elif resource.resource_type=="DocumentReference":
                value=ClinicalNoteReference(**event,note_type="DOCUMENT_REFERENCE",reference=resource.logical_reference);target="clinical_note_references"
            elif resource.resource_type=="Coverage":
                value=ClinicalNoteReference(**event,note_type="COVERAGE",reference=resource.logical_reference);target="clinical_note_references"
            elif resource.resource_type=="CarePlan" and label:
                value=FollowUpPlan(**event,plan=label);target="follow_up_plans"
            elif resource.resource_type=="ImagingStudy":
                modality_code=next((item.get("code") for item in resource.data.get("modality",()) if item.get("code")),None)
                modality={"XR":ImagingModality.XRAY,"MR":ImagingModality.MRI,"CT":ImagingModality.CT,
                    "US":ImagingModality.ULTRASOUND,"NM":ImagingModality.BONE_SCAN}.get(modality_code)
                if modality is None: reasons.append(f"{resource.logical_reference}:UNKNOWN_MODALITY")
                else: value=ImagingStudy(**event,modality=modality,body_site="UNSPECIFIED",
                    findings=(),report_reference=resource.logical_reference);target="imaging_studies"
            if value is not None:
                self._merge(collections[target],value,resource,reasons);mapped.append(resource.logical_reference)
        if reasons:return FhirMappingResult(None,(),self._source(bundle,previous),tuple(sorted(set(reasons))),tuple(mapped))
        identity_entity=PatientIdentity(_stable("identity_",identity.pseudonymous_patient_id),"FHIR_R4","fhir-adapter",
            recorded_at,1.0,f"FHIR|{bundle.fhir_version}|{patient.logical_reference}",identity.pseudonymous_patient_id)
        version=1 if previous is None else previous.version+1
        context_id=_stable("pc_",bundle.content_hash+"|"+(previous.context_id if previous else "genesis"))
        timeline=ClinicalTimeline(_stable("timeline_entity_",timeline_id),"FHIR_R4","fhir-adapter",recorded_at,1.0,
            f"FHIR|{bundle.fhir_version}|{bundle.bundle_id}|{self._policy}",timeline_id,identity.pseudonymous_patient_id,())
        values={key:tuple(value) for key,value in collections.items()}
        if previous is None:
            context=PatientContext(_stable("context_entity_",context_id),"FHIR_R4","fhir-adapter",recorded_at,0.8,
                f"FHIR|{bundle.fhir_version}|{bundle.bundle_id}|{self._policy}",context_id,identity_entity,version,
                None,recorded_at,timeline,retention,sex=sex,**values)
        else:
            context=replace(previous,entity_id=_stable("context_entity_",context_id),source="FHIR_R4",
                author="fhir-adapter",recorded_at=recorded_at,confidence=0.8,
                provenance=f"FHIR|{bundle.fhir_version}|{bundle.bundle_id}|{self._policy}",
                context_id=context_id,version=version,previous_context_id=previous.context_id,
                effective_at=recorded_at,timeline=timeline,retention=retention,sex=sex,**values)
        fields=[]
        for identifier in patient.data.get("identifier",()):
            raw=identifier.get("value")
            if raw: fields.append(ClassifiedClinicalField("national_id",str(raw),DataClassification(ClinicalDataClass.DIRECT_IDENTIFIER,SensitivityLevel.RESTRICTED)))
        for key,value in collections.items():
            if value: fields.append(ClassifiedClinicalField(key,sha256(f"{key}|{len(value)}".encode()).hexdigest(),DataClassification(ClinicalDataClass.CLINICAL_SENSITIVE,SensitivityLevel.HIGH)))
        fields.append(ClassifiedClinicalField("sex",sex.value,DataClassification(ClinicalDataClass.CLINICAL_SENSITIVE,SensitivityLevel.HIGH)))
        return FhirMappingResult(context,tuple(fields),self._source(bundle,previous),(),tuple(mapped))

    def _label(self,resource,reasons):
        code=resource.data.get("code")
        if resource.resource_type in {"AllergyIntolerance","CarePlan"}:
            categories=resource.data.get("category") or ()
            code=resource.data.get("code") or (categories[0] if categories else None)
        if not isinstance(code,dict):
            if resource.resource_type in {"Encounter","DiagnosticReport","DocumentReference","Coverage","ImagingStudy"}: return None
            reasons.append(f"{resource.logical_reference}:MISSING_CODE");return None
        return self._codeable(code,reasons,resource.logical_reference)

    def _codeable(self,codeable,reasons,reference):
        codings=codeable.get("coding",())
        if codings:
            decisions=[]
            for coding in codings:
                if not coding.get("system") or not coding.get("code"):
                    reasons.append(f"{reference}:INVALID_CODING");continue
                decisions.append(self._terminology.validate(coding["system"],coding["code"],coding.get("display")))
            if not decisions or any(not item.accepted or item.review_required for item in decisions):
                reasons.append(f"{reference}:TERMINOLOGY_REVIEW_REQUIRED");return None
            return decisions[0].display or codings[0]["code"]
        text=codeable.get("text")
        if not isinstance(text,str) or not text.strip() or len(text)>256 or any(rx.search(text) for rx in _PHI):
            reasons.append(f"{reference}:UNSAFE_OR_MISSING_TEXT");return None
        return text.strip()

    @staticmethod
    def _status(resource,name):
        coding=((resource.data.get(name) or {}).get("coding") or ())
        return coding[0].get("code").upper() if coding and coding[0].get("code") else None

    @staticmethod
    def _merge(existing,value,resource,reasons):
        current=next((item for item in existing if item.entity_id==value.entity_id),None)
        if current is None: existing.append(value)
        elif current!=value: reasons.append(f"{resource.logical_reference}:CONFLICTING_UPDATE")

    def _source(self,bundle,previous):
        prior=previous.context_id if previous else "GENESIS"
        return f"FHIR|{bundle.fhir_version}|{bundle.bundle_id}|{bundle.content_hash}|{self._policy}|{prior}"
