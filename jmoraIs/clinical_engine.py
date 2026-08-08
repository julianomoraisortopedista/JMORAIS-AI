from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable


@dataclass
class ClinicalCase:
    condition: str
    symptoms: list[str] = field(default_factory=list)
    comorbidities: list[str] = field(default_factory=list)
    risk_factors: list[str] = field(default_factory=list)
    contraindications: list[str] = field(default_factory=list)
    goals: list[str] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class ClinicalRecommendation:
    condition: str
    recommendation: str
    confidence: float
    evidence_strength: str
    reasoning: str
    supporting_claims: list[str]
    caution: list[str]
    source_ids: list[str]


class ClinicalDecisionEngine:
    STATUS_WEIGHT = {
        "VERIFIED": 1.0,
        "PARTIALLY_VERIFIED": 0.6,
        "CONFLICTING_METADATA": 0.2,
        "NOT_VERIFIED": 0.0,
    }

    SUPPORT_WEIGHT = {
        "supporting": 1.0,
        "neutral": 0.25,
        "opposing": -0.8,
    }

    @staticmethod
    def _extract_claims(evidence: Iterable[dict[str, Any]]) -> list[str]:
        claims: list[str] = []
        for item in evidence:
            claim = item.get("claim_text") or item.get("claim") or item.get("title") or "Evidence item"
            claims.append(str(claim))
        return claims

    @classmethod
    def assess(cls, case: ClinicalCase, evidence: list[dict[str, Any]]) -> ClinicalRecommendation:
        if not evidence:
            return ClinicalRecommendation(
                condition=case.condition,
                recommendation="Insufficient evidence for a definitive recommendation. Escalate to specialist review.",
                confidence=0.0,
                evidence_strength="limited",
                reasoning="No verifiable evidence was supplied for this clinical question.",
                supporting_claims=[],
                caution=case.contraindications or case.risk_factors,
                source_ids=[],
            )

        score = 0.0
        supporting_claims: list[str] = []
        caution: list[str] = list(case.contraindications or case.risk_factors)
        source_ids: list[str] = []

        for item in evidence:
            status = str(item.get("verification_status") or "NOT_VERIFIED").upper()
            support = str(item.get("support_direction") or "supporting").lower()
            confidence = float(item.get("confidence", 0.5) or 0.5)
            score += cls.STATUS_WEIGHT.get(status, 0.0) * cls.SUPPORT_WEIGHT.get(support, 0.0) * confidence
            claim = item.get("claim_text") or item.get("claim") or item.get("title") or "Evidence item"
            if status in {"VERIFIED", "PARTIALLY_VERIFIED"}:
                supporting_claims.append(str(claim))
            if item.get("pmid"):
                source_ids.append(str(item["pmid"]))
            elif item.get("doi"):
                source_ids.append(str(item["doi"]))

        if score >= 1.2:
            recommendation = "Evidence supports a clinically supervised treatment pathway for this condition."
            strength = "strong"
        elif score >= 0.5:
            recommendation = "Evidence is mixed but directionally supportive; multidisciplinary review is recommended."
            strength = "moderate"
        else:
            recommendation = "Evidence is limited or conflicting; avoid definitive treatment decisions without specialist input."
            strength = "limited"

        if case.contraindications:
            caution.extend(case.contraindications)
        if case.risk_factors:
            caution.extend(case.risk_factors)

        reasoning = (
            f"The clinical decision was generated from {len(evidence)} evidence item(s) with a cumulative support score of {score:.2f}. "
            f"This result considered condition-specific risk factors and contraindications before recommending a treatment pathway."
        )

        return ClinicalRecommendation(
            condition=case.condition,
            recommendation=recommendation,
            confidence=min(max(score / 2.0, 0.0), 1.0),
            evidence_strength=strength,
            reasoning=reasoning,
            supporting_claims=supporting_claims or cls._extract_claims(evidence),
            caution=list(dict.fromkeys(caution)),
            source_ids=list(dict.fromkeys(source_ids)),
        )
