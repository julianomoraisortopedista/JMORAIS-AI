from dataclasses import FrozenInstanceError,replace
from datetime import date
import pytest
from jmoraIs.guideline_engine import *
from tests.test_guideline_engine import NOW,guideline

def test_governed_source_is_versioned_traceable_and_queryable():
    repository=InMemoryGuidelineSourceRepository();service=GovernedGuidelineSourceService(repository,clock=lambda:NOW)
    first=service.persist(guideline(),appraisal_reference="appraisal-record-1",governance_status="ACTIVE")
    second=service.persist(replace(guideline(),expiration_date=date(2028,1,1)),appraisal_reference="appraisal-record-2",governance_status="ACTIVE")
    assert repository.history(first.guideline_id)==(first,second)
    assert second.predecessor_record_id==first.record_id and second.record_version==2
    assert repository.applicable((first.guideline_id,))==(second.guideline,)
    assert second.provenance_references==("guideline:prov",)
    with pytest.raises(FrozenInstanceError):first.policy_version="tampered"

@pytest.mark.parametrize("status,changes",[("EXPIRED",{"expiration_date":date(2025,1,1)}),("WITHDRAWN",{"withdrawn_at":date(2026,1,1)}),("SUPERSEDED",{"superseded_by":"guideline-2"})])
def test_governance_status_and_temporal_fields_are_preserved(status,changes):
    repository=InMemoryGuidelineSourceRepository();record=GovernedGuidelineSourceService(repository,clock=lambda:NOW).persist(guideline(**changes),appraisal_reference="appraisal-1",governance_status=status)
    assert record.governance_status==status and repository.current(record.guideline_id)==record

def test_ungoverned_or_unappraised_source_is_rejected():
    service=GovernedGuidelineSourceService(InMemoryGuidelineSourceRepository(),clock=lambda:NOW)
    with pytest.raises(GuidelineBoundaryRejected):service.persist("free text",appraisal_reference="a",governance_status="ACTIVE")
    with pytest.raises(GuidelineBoundaryRejected,match="approved appraisal"):service.persist(guideline(appraisal_approved=False),appraisal_reference="a",governance_status="ACTIVE")
