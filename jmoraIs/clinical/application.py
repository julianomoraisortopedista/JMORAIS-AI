"""Deprecated ST-12 application tombstone.

The canonical application service is ``GovernedClinicalIntelligenceService``.
No clinical business rule is retained in this compatibility module.
"""

from .deprecated import DeprecatedClinicalPathError


class ClinicalIntelligenceService:
    def __init__(self, *args, **kwargs) -> None:
        raise DeprecatedClinicalPathError(
            "ST-12 ClinicalIntelligenceService is blocked; use the governed public clinical boundary"
        )

    def evaluate(self, *args, **kwargs):
        raise DeprecatedClinicalPathError(
            "ST-12 ClinicalIntelligenceService is blocked; use the governed public clinical boundary"
        )
