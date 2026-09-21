"""Deprecated pre-governance clinical entry point.

Retained as an import-compatible, fail-closed tombstone until scheduled removal.
"""

from jmoraIs.clinical.deprecated import DeprecatedClinicalPathError


class ClinicalDecisionEngine:
    def __init__(self, *args, **kwargs) -> None:
        raise DeprecatedClinicalPathError(
            "ClinicalDecisionEngine is blocked; use the governed jmoraIs.clinical.ClinicalIntelligenceService"
        )

    def assess(self, *args, **kwargs):
        raise DeprecatedClinicalPathError(
            "ClinicalDecisionEngine is blocked; governed evidence is mandatory"
        )
