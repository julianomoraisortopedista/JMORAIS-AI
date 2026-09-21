from dataclasses import FrozenInstanceError,replace
from datetime import date,datetime,timezone
from decimal import Decimal
import pytest
from jmoraIs.terminology import *

NOW=datetime(2026,8,10,tzinfo=timezone.utc);TODAY=NOW.date()
def source():return TerminologySource("source-1","Institutional test vocabulary","release:test-v1","internal-test-license",NOW,"fixture:terminology")
def version(system=CodeSystem.ORTHOPEDIC,value="1.0"):return TerminologyVersion(f"version-{system.name}-{value}",system,value,date(2026,1,1),None,TerminologyStatus.ACTIVE,source(),"version:fixture")
def code(value="ORTHO:KNEE",display="Knee",version_value="1.0"):return TerminologyCode(CodeSystem.ORTHOPEDIC,value,version_value,display)
def concept(identifier="concept-knee",term="knee",*,synonyms=("knee joint",),status=TerminologyStatus.ACTIVE,category=OrthopedicCategory.JOINT,code_value="ORTHO:KNEE",superseded_by=None):
    return ClinicalConcept(identifier,term.title(),term,synonyms,CodeSystem.ORTHOPEDIC,"1.0",status,date(2026,1,1),None,source(),f"concept:{identifier}",(code(code_value,term.title()),),category,superseded_by)
def setup(*concepts,mappings=()):
    repository=InMemoryTerminologyRepository();repository.append("version:ortho:1",version())
    for item in concepts:repository.append(item.canonical_id,item)
    for item in mappings:repository.append(item.mapping_id,item)
    audit=InMemoryTerminologyAuditAdapter();units=DeterministicUcumAdapter((UnitConversionRule("mg","g",Decimal("0.001"),Decimal("0"),"2.2","UCUM fixture conversion"),))
    return ClinicalTerminologyService(repository,audit,units,clock=lambda:NOW),repository,audit

def test_supported_code_systems_and_orthopedic_categories_are_explicit():
    assert {item.value for item in CodeSystem}=={"ICD-10","ICD-11","SNOMED_CT","LOINC","RxNorm","ATC","UCUM","TUSS","CPT_REFERENCE_ONLY","JMORAIS_ORTHOPEDIC"}
    assert {item.value for item in OrthopedicCategory}=={"BONE","JOINT","LIGAMENT","TENDON","CARTILAGE","MENISCUS","MUSCLE","LATERALITY","BODY_REGION","ROM","ALIGNMENT","INSTABILITY","SPORTS_ACTIVITY","FUNCTIONAL_LIMITATION"}

def test_canonical_and_synonym_mapping_are_deterministic_and_immutable():
    item=concept();service,_,audit=setup(item)
    exact=service.normalize_terminology("knee",CodeSystem.ORTHOPEDIC,"1.0")
    synonym=service.resolve_concepts("knee joint",CodeSystem.ORTHOPEDIC,"1.0")
    assert exact.selected_concept_id==item.canonical_id and exact.confidence is MappingConfidence.HIGH
    assert synonym.selected_concept_id==item.canonical_id and synonym.confidence is MappingConfidence.MEDIUM
    assert len(audit.history("knee"))==1
    with pytest.raises(FrozenInstanceError):item.status=TerminologyStatus.RETIRED

def test_ambiguous_mapping_keeps_all_candidates_and_requires_review():
    first=concept("concept-joint",term="joint",synonyms=("articulation",),code_value="ORTHO:JOINT")
    second=concept("concept-junction",term="junction",synonyms=("articulation",),code_value="ORTHO:JUNCTION")
    service,_,audit=setup(first,second);result=service.normalize_terminology("articulation",CodeSystem.ORTHOPEDIC,"1.0")
    assert result.outcome is MappingOutcome.REVIEW_REQUIRED and result.review_required
    assert {item.canonical_id for item in result.candidates}=={"concept-joint","concept-junction"}
    assert audit.history("articulation")[0].event_type is TerminologyAuditType.AMBIGUOUS_MAPPING

def test_unknown_mapping_never_invents_a_candidate():
    result=setup(concept())[0].resolve_concepts("not in governed vocabulary",CodeSystem.ORTHOPEDIC,"1.0")
    assert result.outcome is MappingOutcome.UNKNOWN and result.candidates==() and result.selected_concept_id is None

@pytest.mark.parametrize("status,successor,issue",[(TerminologyStatus.DEPRECATED,None,"DEPRECATED"),(TerminologyStatus.SUPERSEDED,"concept-new","SUPERSEDED"),(TerminologyStatus.RETIRED,None,"RETIRED"),(TerminologyStatus.UNKNOWN,None,"UNKNOWN")])
def test_non_active_concepts_are_preserved_but_fail_validation(status,successor,issue):
    item=concept(status=status,superseded_by=successor);service,_,_=setup(item)
    result=service.validate_concept(item,as_of=TODAY)
    assert not result.valid and issue in result.issues

def test_version_lookup_is_explicit_and_unknown_version_fails_closed():
    service,_,audit=setup(concept());assert service.version_lookup(CodeSystem.ORTHOPEDIC,"1.0").status is TerminologyStatus.ACTIVE
    with pytest.raises(InvalidTerminologyRecord):service.version_lookup(CodeSystem.ORTHOPEDIC,"absent")
    assert len(audit.history(CodeSystem.ORTHOPEDIC.value))==2

def test_one_to_many_many_to_one_and_ambiguous_code_mapping_are_retained():
    src=code("ORTHO:SOURCE","Source");a=code("ORTHO:A","A");b=code("ORTHO:B","B")
    one_many=ConceptMapping("map-one-many",(src,),(a,b),MappingConfidence.MEDIUM,TerminologyStatus.ACTIVE,TODAY,None,source(),"mapping:one-many")
    many_one=ConceptMapping("map-many-one",(a,b),(src,),MappingConfidence.HIGH,TerminologyStatus.ACTIVE,TODAY,None,source(),"mapping:many-one")
    service,_,audit=setup(mappings=(one_many,many_one))
    assert service.map_codes((src,),CodeSystem.ORTHOPEDIC)==(one_many,)
    assert service.map_codes((a,b),CodeSystem.ORTHOPEDIC)==(many_one,)
    assert audit.history("ORTHO:SOURCE")[0].event_type is TerminologyAuditType.AMBIGUOUS_MAPPING

def test_ucum_normalization_preserves_original_and_conversion_provenance():
    service,_,audit=setup();result=service.normalize_unit("1250","mg","g","2.2")
    assert result.original_value==Decimal("1250") and result.original_unit=="mg"
    assert result.normalized_value==Decimal("1.250") and result.normalized_unit=="g" and result.conversion_provenance
    assert audit.history("mg->g")[0].event_type is TerminologyAuditType.NORMALIZATION
    with pytest.raises(UnknownUnitConversion):service.normalize_unit(1,"unknown","g","2.2")

def test_repository_is_append_only_and_retains_version_history():
    item=concept();_,repository,_=setup(item);retired=replace(item,status=TerminologyStatus.RETIRED,retirement_date=TODAY)
    repository.append(item.canonical_id,retired)
    assert repository.history(item.canonical_id)==(item,retired) and repository.latest(item.canonical_id)==retired
    with pytest.raises(TerminologyVersionConflict):repository.append(item.canonical_id,retired)
