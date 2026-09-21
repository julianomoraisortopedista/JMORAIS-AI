from datetime import datetime,timezone
from jmoraIs.clinical_state.domain import *
from jmoraIs.orthopedic_intelligence import *
from jmoraIs.terminology import *
from tests.test_terminology import concept,setup

NOW=datetime(2026,8,10,tzinfo=timezone.utc)
def state(version=1,previous=None,review=ClinicalReviewStatus.REVIEW_REQUIRED):
    ortho=OrthopedicState("ortho-1",None,"knee","left",("limited rom",),"alignment abnormality",("lachman",),("locking",),None,(),None,None,(),(),(),"prov:ortho")
    flag=DataQualityFlag(DataQualityFlagType.CONFLICTING_DATA,("ortho-1",),"conflict")
    return PatientClinicalState(f"state-{version}","pt_"+"a"*64,"context-1",1,version,previous,NOW,review,orthopedic=(ortho,),quality_flags=(flag,),provenance_references=("prov:state",))
def terminology_records():
    terms=(("knee",OrthopedicCategory.JOINT),("left",OrthopedicCategory.LATERALITY),("limited rom",OrthopedicCategory.ROM),("alignment abnormality",OrthopedicCategory.ALIGNMENT),("lachman",OrthopedicCategory.INSTABILITY),("locking",OrthopedicCategory.FUNCTIONAL_LIMITATION))
    return tuple(concept(f"concept-{index}",term=term,synonyms=(),category=category,code_value=f"ORTHO:{index}") for index,(term,category) in enumerate(terms))
def terminology():return setup(*terminology_records())[0]
def test_projection_is_deterministic_versioned_and_preserves_governance():
    service=OrthopedicStateProjectionService(terminology());first=service.project(state(),"1.0");second=service.project(state(2,"state-1"),"1.0")
    assert first==service.project(state(),"1.0")
    assert first.subject_reference.startswith("pt_") and first.state_version==first.projection_version==1
    assert second.predecessor_projection_reference=="state-1" and second.projection_version==2
    assert {x.category for x in first.findings}>={FindingCategory.LOCKING,FindingCategory.LIMITED_ROM,FindingCategory.ALIGNMENT_ABNORMALITY}
    assert first.stability_findings[0].epistemic_status=="OBSERVED"
    assert {"CONFLICTING_DATA","REVIEW_REQUIRED"}<=set(first.quality_flags)
    assert first.provenance_references==("prov:state",)
