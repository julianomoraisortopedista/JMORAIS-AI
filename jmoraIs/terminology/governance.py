from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
import json

from .domain import *


def mapping_governance_integrity_hash(record):
    payload=asdict(record);payload.pop("integrity_hash",None)
    encoded=json.dumps(payload,sort_keys=True,separators=(",",":"),default=lambda value:value.value if isinstance(value,Enum) else value.isoformat())
    return sha256(encoded.encode()).hexdigest()


class TerminologyMappingGovernanceService:
    def __init__(self,repository,*,clock=None):self._repository=repository;self._clock=clock or (lambda:datetime.now(timezone.utc))
    def persist(self,mapped,*,source_reference,target_concept_id,mapping_type,review_status,review_required,
                mapping_method,policy_version,reviewer_reference=None):
        if not isinstance(mapped,MappedClinicalConcept):raise InvalidTerminologyRecord("canonical MappedClinicalConcept is required")
        if not isinstance(mapping_type,MappingType) or not isinstance(review_status,MappingReviewStatus):raise InvalidTerminologyRecord("typed mapping governance is required")
        candidates={item.canonical_id for item in mapped.candidates}
        if mapping_type is MappingType.UNMAPPED:
            if mapped.outcome is not MappingOutcome.UNKNOWN or target_concept_id is not None:raise InvalidTerminologyRecord("unmapped governance must preserve unknown mapping")
        elif target_concept_id not in candidates:raise InvalidTerminologyRecord("target concept is not a canonical mapping candidate")
        if mapped.outcome is MappingOutcome.MAPPED and target_concept_id!=mapped.selected_concept_id:raise InvalidTerminologyRecord("selected mapping target mismatch")
        if mapped.outcome is MappingOutcome.REVIEW_REQUIRED and (not review_required or review_status is not MappingReviewStatus.REVIEW_REQUIRED):raise InvalidTerminologyRecord("ambiguous mapping must remain review-required")
        if not mapped.provenance_references:
            raise InvalidTerminologyRecord("canonical mapping provenance is required")
        stream=target_concept_id or "unmapped:"+source_reference;previous=self._repository.current_by_concept(stream);version=1 if previous is None else previous.version+1
        created=self._clock();identifier="tmg_"+sha256(f"{stream}|{version}|{source_reference}|{policy_version}".encode()).hexdigest()
        unsigned=TerminologyMappingGovernanceRecord(identifier,source_reference,mapped.original_term,mapped.requested_code_system,
          target_concept_id,mapped.terminology_version,mapping_type,mapped.confidence,review_status,review_required,
          reviewer_reference,mapping_method,policy_version,mapped.provenance_references,created,
          version,previous.governance_record_id if previous else None,"pending")
        record=TerminologyMappingGovernanceRecord(**{**unsigned.__dict__,"integrity_hash":mapping_governance_integrity_hash(unsigned)})
        self._repository.append(record);return record
