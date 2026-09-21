from __future__ import annotations
from datetime import datetime,timezone
from hashlib import sha256
from .domain import GovernedGuidelineRecord,GovernedGuidelineRecommendation,GuidelineBoundaryRejected

class GovernedGuidelineSourceService:
    def __init__(self,repository,*,clock=None):self._repository=repository;self._clock=clock or (lambda:datetime.now(timezone.utc))
    def persist(self,guideline,*,appraisal_reference,governance_status):
        if not isinstance(guideline,GovernedGuidelineRecommendation):raise GuidelineBoundaryRejected("typed governed guideline is required")
        if not guideline.appraisal_approved:raise GuidelineBoundaryRejected("approved appraisal is required")
        previous=self._repository.current(guideline.guideline_id);version=1 if previous is None else previous.record_version+1
        identity="ggs_"+sha256(f"{guideline.guideline_id}|{guideline.guideline_version}|{version}".encode()).hexdigest()
        value=GovernedGuidelineRecord(identity,guideline.guideline_id,guideline.guideline_version,version,
          previous.record_id if previous else None,governance_status,guideline,appraisal_reference,guideline.appraisal_version,
          guideline.provenance_references,guideline.policy_version,self._clock())
        self._repository.append(value);return value
