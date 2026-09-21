from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

from jmoraIs.medical_documents import DocumentOrthopedicLineageStatus,DocumentType
from jmoraIs.orthopedic_intelligence import (InMemoryOrthopedicAssessmentRepository,
    OrthopedicBoundaryError,PersistedOrthopedicAssessmentSetReference)
from jmoraIs.tenancy.context import TenantContextBinder
from jmoraIs.tenancy.domain import TenantContext
from tests.test_medical_document_engine import setup as document_setup
from tests.test_orthopedic_intelligence import engine,finding,view

def context(tenant="tenant-orthopedic"):
    return TenantContext(tenant,"org-"+tenant,"principal","INTERNAL_SERVICE","CLINICAL_VALIDATION","iam-policy-v1","corr-orthopedic")

def test_owner_reference_is_exact_and_fabrication_fails_closed():
    service,repository,_,reasoning=engine(view(finding()));value=service.generate(reasoning);binder=TenantContextBinder()
    with binder.bind_tenant(context()):
        reference=repository.reference_for(value);assert repository.get_exact(reference)==value
        forged=(replace(reference,set_id="ortho_"+"0"*64),replace(reference,set_version=2),replace(reference,subject_reference="pt_"+"0"*64),replace(reference,policy_version="wrong"),replace(reference,integrity_hash="0"*64),PersistedOrthopedicAssessmentSetReference("osr_"+uuid4().hex,reference.set_id,reference.set_version,reference.subject_reference,reference.tenant_id,reference.policy_version,reference.integrity_hash,reference.issued_at))
        for item in forged:
            with pytest.raises(OrthopedicBoundaryError):repository.get_exact(item)
    with binder.bind_tenant(context("tenant-other")):
        with pytest.raises(OrthopedicBoundaryError):repository.get_exact(reference)
    with pytest.raises(Exception):repository.get_exact(reference)

def test_legacy_document_is_explicitly_ineligible_for_exact_orthopedic_lineage():
    service,_,_,input_value=document_setup();document=service.generate(input_value,DocumentType.PROCEDURE_JUSTIFICATION_DRAFT)
    assert document.document.orthopedic_assessment_set_reference is None
    assert document.orthopedic_lineage_status is DocumentOrthopedicLineageStatus.LEGACY_MISSING_ORTHOPEDIC_ASSESSMENT_REFERENCE

def test_architecture_keeps_owner_issuance_and_controlled_path_uses_get_exact():
    root=Path(__file__).parents[1];owner=(root/"jmoraIs/orthopedic_intelligence/persistence.py").read_text();medical=(root/"jmoraIs/medical_documents/application.py").read_text();production="\n".join(path.read_text() for path in (root/"jmoraIs").rglob("*.py"))
    assert "def reference_for(self,value)" in owner and "def get_exact(self,reference)" in owner
    assert "self._orthopedic.get_exact(reference)" in medical and "def generate_controlled" in medical
    assert "evaluation.e2e_acceptance" not in production
