from dataclasses import replace
import pytest
from jmoraIs.medical_documents import *
from jmoraIs.terminology import TerminologyStatus
from tests.test_terminology import concept

class Repository:
    def __init__(self,value):self.value=value
    def latest(self,identifier):return self.value if self.value and self.value.canonical_id==identifier else None

@pytest.mark.parametrize("status,successor",[(TerminologyStatus.ACTIVE,None),(TerminologyStatus.DEPRECATED,None),(TerminologyStatus.RETIRED,None),(TerminologyStatus.SUPERSEDED,"replacement"),(TerminologyStatus.UNKNOWN,None)])
def test_projection_preserves_status_version_provenance_and_review(status,successor):
    value=concept(status=status,superseded_by=successor);result=PostgreSQLGovernedDocumentTerminologyAdapter(Repository(value)).get(value.canonical_id)
    assert result.concept_id==value.canonical_id and result.version==value.version
    assert result.code_system==value.code_system.value and value.provenance in result.provenance_references
    assert result.review_required is (status is not TerminologyStatus.ACTIVE)
    assert result.mapping_status==(status.value if status is not TerminologyStatus.ACTIVE else "MAPPED")
    assert result.confidence==("HIGH" if status is TerminologyStatus.ACTIVE else "UNKNOWN")
def test_unknown_identifier_never_invents_terminology():
    assert PostgreSQLGovernedDocumentTerminologyAdapter(Repository(None)).get("missing") is None
def test_document_validation_gate_preserves_terminology_review_requirement():
    value=concept(status=TerminologyStatus.DEPRECATED);term=PostgreSQLGovernedDocumentTerminologyAdapter(Repository(value)).get(value.canonical_id)
    section=DocumentSection("facts","Facts",1,(SourceType.TERMINOLOGY,),(),(),(),(term,),(),term.provenance_references)
    template=DocumentTemplate("template",DocumentType.CLINICAL_REPORT,"1",("facts",),("facts",),(),(("facts",(SourceType.TERMINOLOGY,)),),(),"policy")
    from tests.test_medical_document_engine import NOW
    result=DocumentValidationGate(clock=lambda:NOW).validate((section,),template)
    assert any(x.code=="TERMINOLOGY_UNCERTAINTY" for x in result.issues)
