#!/usr/bin/env python3
"""Populate the disposable release-validation database through public ports."""
from datetime import date
import os
import sys
from pathlib import Path
from sqlalchemy import create_engine
from jmoraIs.application import ScientificEvidencePackagePort
from jmoraIs.appraisal import ClinicalAppraisalService, GovernedEvidenceService
from jmoraIs.appraisal.persistence import SQLAlchemyGovernedEvidenceRepository
from jmoraIs.clinical import (AuthorizedRecommendationReviewService, ConflictAdjudicationService,
 ConflictAdjudicationState, GovernedClinicalIntelligenceService, GovernedEvidenceEligibilityGate,
 GovernedEvidenceReevaluationService, GovernedRecommendationCandidate, HumanReviewStatus,
 ReviewAuthorizationPolicy, ReviewerIdentity, ReviewerRole)
from jmoraIs.clinical.governance_persistence import (PostgreSQLReviewerIdentityRepository,
 SQLAlchemyConflictAdjudicationRepository, SQLAlchemyGovernedDecisionAuditRepository,
 SQLAlchemyGovernedEvidenceLifecycleRepository)
from jmoraIs.evidence_ledger import LedgerEventType
from jmoraIs.infrastructure.postgresql_package_catalog import PostgreSQLCanonicalLedger, PostgreSQLPackageCatalogRepository
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"tests"))
from test_clinical_appraisal_domain import TODAY, request
from test_evidence_package_boundary import NOW, populated_ledger, verified_article

def main(url):
    engine=create_engine(url,future=True);catalog=PostgreSQLPackageCatalogRepository(engine)
    source,claim_id,_=populated_ledger();ledger=PostgreSQLCanonicalLedger(engine)
    claim,fragment,support=source.claims[0],source.fragments[0],source.supports[0]
    ledger.create_claim(claim.claim_text,claim_id=claim.claim_id,created_at=claim.created_at)
    _,first,_=ledger.register_evidence(claim_id=claim_id,source_name=fragment.source_name,source_type=fragment.source_type,
      passage=fragment.passage,payload_hash=fragment.payload_hash,retrieved_at=fragment.retrieved_at,
      verification_version=fragment.verification_version,pipeline_version=fragment.pipeline_version,
      policy_version=fragment.policy_version,support_direction=support.support_direction,pmid=fragment.pmid,occurred_at=fragment.created_at)
    packages=ScientificEvidencePackagePort(catalog=catalog,clock=lambda:NOW)
    old=packages.issue(article=verified_article(),ledger=ledger,claim_id=claim_id,support_ids=(first.support_id,),pipeline_version="ST-24")
    _,replacement,_=ledger.register_evidence(claim_id=claim_id,source_name="PubMed",source_type="pubmed",passage="replacement evidence",
      payload_hash="d"*64,retrieved_at=NOW,verification_version="ST-24",pipeline_version="ST-24",policy_version="ST-02",
      support_direction="supporting",pmid="12345678",occurred_at=NOW)
    ledger.append_lifecycle_event(claim_id=claim_id,event_type=LedgerEventType.SUPERSESSION,
      target_support_id=first.support_id,replacement_support_id=replacement.support_id,occurred_at=NOW)
    active=packages.issue(article=verified_article(),ledger=ledger,claim_id=claim_id,support_ids=(replacement.support_id,),pipeline_version="ST-24")
    governed_repo=SQLAlchemyGovernedEvidenceRepository(engine)
    appraisal_request=request("representative",package_id=active.package_id)
    appraisal=ClinicalAppraisalService(packages).assess((appraisal_request,),as_of=TODAY)[0][0]
    governed=GovernedEvidenceService(packages,governed_repo,clock=lambda:NOW)
    evidence=governed.issue(appraisal,appraisal_request);governed.issue(appraisal,appraisal_request)
    audit=SQLAlchemyGovernedDecisionAuditRepository(engine);lifecycle_repo=SQLAlchemyGovernedEvidenceLifecycleRepository(engine)
    lifecycle=GovernedEvidenceReevaluationService(packages,lifecycle_repo,clock=lambda:NOW)
    clinical=GovernedClinicalIntelligenceService(governed,audit,GovernedEvidenceEligibilityGate(lifecycle),clock=lambda:NOW)
    recommendation=clinical.evaluate(case_id="release-case",candidates=(GovernedRecommendationCandidate(
      "release-candidate","Representative governed recommendation",(evidence.governed_evidence_id,),("ADULT",)),))[0]
    identities=PostgreSQLReviewerIdentityRepository(engine)
    reviewer=ReviewerIdentity("release-reviewer",ReviewerRole.SENIOR_REVIEWER,organization_id="release-org",tenant_id="release-tenant",created_at=NOW,updated_at=NOW)
    identities.save(reviewer)
    AuthorizedRecommendationReviewService(identities,audit,ReviewAuthorizationPolicy(),clock=lambda:NOW).transition(
      case_id="release-case",recommendation=recommendation,target=HumanReviewStatus.APPROVED_BY_REVIEWER,
      reviewer_id=reviewer.reviewer_id,justification="Representative release review.",generated_by="system")
    conflicts=ConflictAdjudicationService(SQLAlchemyConflictAdjudicationRepository(engine),identities,clock=lambda:NOW)
    opened=conflicts.transition(conflict_id="release-conflict",case_id="release-case",target=ConflictAdjudicationState.OPEN,
      directions=("SUPPORTING","OPPOSING"),reviewer_id=reviewer.reviewer_id,justification="Representative conflict.")
    conflicts.transition(conflict_id="release-conflict",case_id="release-case",target=ConflictAdjudicationState.UNDER_REVIEW,
      directions=opened.directions,reviewer_id=reviewer.reviewer_id,justification="Representative review.")
    GovernedEvidenceReevaluationService(packages,lifecycle_repo,policy_version="ST-24-CHANGED",clock=lambda:NOW).evaluate(
      evidence,as_of=date(2026,1,1))
    ledger.append_lifecycle_event(claim_id=claim_id,event_type=LedgerEventType.RETRACTION,
      target_support_id=replacement.support_id,reason="Representative retraction",occurred_at=NOW)
    print({"old_package":old.package_id,"active_then_retracted_package":active.package_id,
           "governed_evidence":evidence.governed_evidence_id,"case":"release-case"})

if __name__=="__main__": main(os.environ["JMORAIS_TEST_POSTGRES_URL"])
