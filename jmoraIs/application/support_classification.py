"""AI-proposed, physician-confirmed support direction of a publication for a claim.

The model only *proposes* SUPPORTING / OPPOSING / NEUTRAL / INCONCLUSIVE through the
Canonical LLM Gateway (human review mandatory, never externally actionable). A
proposal is usable only if its quote is a verbatim passage of the published PubMed
abstract; otherwise it is UNGROUNDED. Nothing reaches the evidence ledger until a
physician ACCEPTs or OVERRIDEs it, and the ledger records model and prompt versions.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from hashlib import sha256
import json
import re
from typing import Callable, Optional
from uuid import uuid4

from jmoraIs.connect.pubmed import PublishedAbstract
from jmoraIs.evidence_ledger import AppendOnlyEvidenceLedger
from jmoraIs.llm_gateway.domain import (
    CanonicalStructuredDTO, LLMModel, LLMOutputClassification, LLMRequest, ReviewPolicy, StructuredField,
)
from jmoraIs.scientific_domain import SupportDirection

POLICY = "MIP-10.1"
SCHEMA_ID = "support-classification-input"
SCHEMA_VERSION = "1"
OUTPUT_SCHEMA_ID = "support-classification-output-v1"
CLASSIFIER_VERSION = "support-classification-v1"
MIN_QUOTE_CHARS = 20
MAX_OUTPUT_TOKENS = 4000  # includes model reasoning on current Claude models
OUTPUT_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "direction": {"type": "string", "enum": [d.value for d in SupportDirection]},
        "quote": {"type": "string"},
        "rationale": {"type": "string"},
    },
    "required": ["direction", "quote", "rationale"],
    "additionalProperties": False,
}
INSTRUCTIONS = (
    "You assist a physician. Given CLAIM and a PubMed ABSTRACT, decide whether the abstract is "
    "SUPPORTING, OPPOSING, NEUTRAL or INCONCLUSIVE for the claim. Use only the abstract. Copy one "
    "exact sentence or clause from the abstract that justifies the decision. Reply with JSON only: "
    '{"direction": "...", "quote": "...", "rationale": "..."}. This is a draft for physician review.'
)


class SupportClassificationRejected(ValueError):
    pass


class ProposalStatus(str, Enum):
    PENDING_PHYSICIAN_REVIEW = "PENDING_PHYSICIAN_REVIEW"
    UNGROUNDED = "UNGROUNDED"
    BLOCKED = "BLOCKED"


class PhysicianDecisionType(str, Enum):
    ACCEPT = "ACCEPT"
    OVERRIDE = "OVERRIDE"
    REJECT = "REJECT"


@dataclass(frozen=True)
class SupportClassificationProposal:
    proposal_id: str
    claim: str
    pmid: str
    abstract_hash: str
    source_locator: str
    status: ProposalStatus
    proposed_direction: Optional[SupportDirection]
    quote: Optional[str]
    rationale: str
    request_id: str
    model_id: str
    prompt_version_id: str
    created_at: datetime


@dataclass(frozen=True)
class PhysicianSupportDecision:
    decision_id: str
    proposal: SupportClassificationProposal
    decision: PhysicianDecisionType
    final_direction: Optional[SupportDirection]
    reviewer_id: str
    note: str
    decided_at: datetime

    @property
    def usable(self) -> bool:
        return self.decision is not PhysicianDecisionType.REJECT


def _normalize(text: str) -> str:
    return " ".join(text.split()).casefold()


def _is_verbatim(quote: str, abstract: PublishedAbstract) -> bool:
    # Section labels ("RESULTS: ") are added by the parser, never part of a quote.
    body = re.sub(r"(?m)^[A-Z][A-Z /&-]{1,40}: ", "", abstract.text)
    return len(quote.strip()) >= MIN_QUOTE_CHARS and _normalize(quote) in _normalize(body)


class SupportClassificationService:
    def __init__(self, gateway, *, prompt_version_id: str, model: LLMModel,
                 clock: Callable[[], datetime], id_factory: Callable[[], str] = lambda: uuid4().hex):
        self._gateway = gateway
        self._prompt_version_id = prompt_version_id
        self._model = model
        self._clock = clock
        self._ids = id_factory

    def propose(self, claim: str, abstract: PublishedAbstract) -> SupportClassificationProposal:
        claim = " ".join((claim or "").split())
        if len(claim) < 10:
            raise SupportClassificationRejected("a specific claim is required")
        if not isinstance(abstract, PublishedAbstract) or sha256(abstract.text.encode("utf-8")).hexdigest() != abstract.content_hash:
            raise SupportClassificationRejected("integrity-checked PubMed abstract is required")
        dto = CanonicalStructuredDTO(SCHEMA_ID, SCHEMA_VERSION, (
            StructuredField("claim", claim, "physician-question"),
            StructuredField("pmid", abstract.pmid, abstract.source_locator),
            StructuredField("title", abstract.title, abstract.source_locator),
            StructuredField("abstract", abstract.text, abstract.source_locator),
        ), POLICY, (abstract.source_locator, "sha256:" + abstract.content_hash))
        request_id = "scls-" + self._ids()
        response = self._gateway.invoke(LLMRequest(
            request_id, self._prompt_version_id, self._model, dto,
            ReviewPolicy("physician-support-review", POLICY, True, False),
            0.0, None, MAX_OUTPUT_TOKENS, POLICY, self._clock()))
        status, direction, quote, rationale = self._interpret(response, abstract)
        return SupportClassificationProposal(
            "prop-" + self._ids(), claim, abstract.pmid, abstract.content_hash, abstract.source_locator,
            status, direction, quote, rationale, request_id, self._model.model_id,
            self._prompt_version_id, self._clock())

    @staticmethod
    def _interpret(response, abstract):
        if response.classification is LLMOutputClassification.BLOCKED:
            return ProposalStatus.BLOCKED, None, None, "model output blocked by gateway policy"
        text = response.output_text.strip()
        match = re.search(r"\{.*\}", text, re.DOTALL)
        try:
            data = json.loads(match.group(0) if match else text)
            direction = SupportDirection(str(data["direction"]).strip().upper())
            quote = " ".join(str(data["quote"]).split())
            rationale = " ".join(str(data.get("rationale", "")).split())[:1000]
        except (ValueError, KeyError, TypeError, AttributeError):
            return ProposalStatus.UNGROUNDED, None, None, "model output is not the governed JSON schema"
        if not _is_verbatim(quote, abstract):
            return ProposalStatus.UNGROUNDED, direction, None, "quote is not a verbatim passage of the abstract"
        return ProposalStatus.PENDING_PHYSICIAN_REVIEW, direction, quote, rationale

    def decide(self, proposal: SupportClassificationProposal, *, reviewer_id: str,
               decision: PhysicianDecisionType, final_direction: Optional[SupportDirection] = None,
               note: str = "") -> PhysicianSupportDecision:
        if not reviewer_id or not reviewer_id.strip():
            raise SupportClassificationRejected("identified physician reviewer is required")
        if decision is PhysicianDecisionType.REJECT:
            final = None
        elif proposal.status is not ProposalStatus.PENDING_PHYSICIAN_REVIEW:
            raise SupportClassificationRejected("only grounded proposals can be accepted or overridden")
        elif decision is PhysicianDecisionType.ACCEPT:
            if final_direction not in (None, proposal.proposed_direction):
                raise SupportClassificationRejected("ACCEPT keeps the proposed direction; use OVERRIDE")
            final = proposal.proposed_direction
        elif decision is PhysicianDecisionType.OVERRIDE:
            if not isinstance(final_direction, SupportDirection) or final_direction is proposal.proposed_direction:
                raise SupportClassificationRejected("OVERRIDE requires a different direction")
            if not note.strip():
                raise SupportClassificationRejected("OVERRIDE requires the physician's reason")
            final = final_direction
        else:
            raise SupportClassificationRejected("unknown decision")
        return PhysicianSupportDecision("dec-" + self._ids(), proposal, decision, final,
                                        reviewer_id.strip(), note.strip(), self._clock())


def register_confirmed_support(decision: PhysicianSupportDecision, *, ledger: AppendOnlyEvidenceLedger,
                               claim_id: str, doi: Optional[str] = None):
    """Only physician-confirmed, grounded classifications enter the evidence ledger."""
    if not isinstance(decision, PhysicianSupportDecision) or not decision.usable:
        raise SupportClassificationRejected("a physician-confirmed decision is required")
    proposal = decision.proposal
    return ledger.register_evidence(
        claim_id=claim_id, source_name="NCBI PubMed", source_type="pubmed", passage=proposal.quote,
        payload_hash=proposal.abstract_hash, retrieved_at=proposal.created_at,
        verification_version="ST-02", pipeline_version=CLASSIFIER_VERSION, policy_version=POLICY,
        support_direction=decision.final_direction.value, source_locator=proposal.source_locator,
        exact_location="abstract", pmid=proposal.pmid, doi=doi,
        model_version=proposal.model_id, prompt_version=proposal.prompt_version_id,
        occurred_at=decision.decided_at)


def support_classification_prompt():
    from jmoraIs.llm_gateway.domain import PromptTemplate
    return PromptTemplate(CLASSIFIER_VERSION, "Support direction proposal",
                          "Propose support direction of a publication for physician review",
                          INSTRUCTIONS, ("CanonicalStructuredDTO",), OUTPUT_SCHEMA_ID, POLICY)
