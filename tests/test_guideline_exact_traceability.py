from dataclasses import replace
from pathlib import Path
from uuid import uuid4
import pytest
from jmoraIs.guideline_engine import GuidelineBoundaryRejected,InMemoryRecommendationRepository,PersistedGuidelineRecommendationSetReference
from jmoraIs.medical_documents import DocumentGuidelineLineageStatus,DocumentType
from jmoraIs.tenancy.context import TenantContextBinder
from jmoraIs.tenancy.domain import TenantContext
from tests.test_guideline_engine import ready_input,setup
from tests.test_medical_document_engine import setup as document_setup

def _context(tenant="tenant-guideline"):
    return TenantContext(tenant,"org-"+tenant,"principal","INTERNAL_SERVICE","CLINICAL_VALIDATION","iam-policy-v1","corr-guideline")

def _persisted_set(repository):
    suffix=uuid4().hex
    value=setup()[0].create_recommendation_set(replace(ready_input(),input_id="ri_"+suffix*2,subject_reference="pt_"+suffix*2))
    repository.append(value);return value

def test_owner_reference_is_exact_and_fabrication_fails_closed():
    repository=InMemoryRecommendationRepository();binder=TenantContextBinder()
    with binder.bind_tenant(_context()):
        value=_persisted_set(repository);reference=repository.reference_for(value)
        assert repository.get_exact(reference)==value
        for forged in (replace(reference,set_id="gr_"+"0"*64),replace(reference,set_version=2),replace(reference,subject_reference="pt_"+"0"*64),replace(reference,policy_version="wrong"),replace(reference,integrity_hash="0"*64),PersistedGuidelineRecommendationSetReference("gsr_"+uuid4().hex,reference.set_id,reference.set_version,reference.subject_reference,reference.tenant_id,reference.policy_version,reference.integrity_hash,reference.issued_at)):
            with pytest.raises(GuidelineBoundaryRejected):repository.get_exact(forged)
    with binder.bind_tenant(_context("tenant-other")):
        with pytest.raises(GuidelineBoundaryRejected):repository.get_exact(reference)
    with pytest.raises(Exception):repository.get_exact(reference)

def test_legacy_document_is_explicitly_ineligible_for_exact_lineage():
    service,_,_,input_value=document_setup();document=service.generate(input_value,DocumentType.PROCEDURE_JUSTIFICATION_DRAFT)
    assert document.document.guideline_recommendation_set_reference is None
    assert document.guideline_lineage_status is DocumentGuidelineLineageStatus.LEGACY_MISSING_GUIDELINE_SET_REFERENCE

def test_architecture_keeps_owner_issuance_and_no_e2e_dependency():
    root=Path(__file__).parents[1];guideline=(root/"jmoraIs/guideline_engine/persistence.py").read_text();medical=(root/"jmoraIs/medical_documents/application.py").read_text();document_domain=(root/"jmoraIs/medical_documents/domain.py").read_text();production="\n".join(path.read_text() for path in (root/"jmoraIs").rglob("*.py"))
    assert "def reference_for(self,value)" in guideline and "def get_exact(self,reference)" in guideline
    assert "source=self._guidelines.get_exact(reference)" in medical and "guideline_recommendation_set_reference" in document_domain
    assert "evaluation.e2e_acceptance" not in production
