"""Portuguese clinical question -> English claim + PICO terms for the PubMed search.

The model only drafts the search; nothing it returns is evidence. Output terms must pass
the same PICOQuestion safety rules used for typed searches (no query syntax), and the
physician sees and can edit every field before searching. Generic identifier patterns
are removed from the question before it leaves the server.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import re
from typing import Callable
from uuid import uuid4

from jmoraIs.application.deidentification import deidentify
from jmoraIs.application.evidence_query import STUDY_DESIGN_FILTERS, EvidenceQueryRejected, PICOQuestion
from jmoraIs.llm_gateway.domain import (
    CanonicalStructuredDTO, LLMModel, LLMOutputClassification, LLMRequest, PromptTemplate, ReviewPolicy, StructuredField,
)

POLICY = "MIP-10.1"
PROMPT_ID = "question-to-pico-v1"
INSTRUCTIONS = (
    "You help an orthopaedic surgeon search PubMed. Convert the Portuguese clinical question (and, when given, "
    "the procedure and implant/OPME context) into: a specific English claim to be supported or refuted; PICO "
    "synonym lists in English using standard medical terms (2-4 short synonyms each; population and intervention "
    "required; comparison and outcome optional); and study designs among rct, sr, ma, guideline. Use plain words "
    "only: no quotes, brackets, AND/OR/NOT or field tags. Do not include patient data. Reply with JSON only."
)
OUTPUT_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "claim": {"type": "string"},
        "population": {"type": "array", "items": {"type": "string"}},
        "intervention": {"type": "array", "items": {"type": "string"}},
        "comparison": {"type": "array", "items": {"type": "string"}},
        "outcome": {"type": "array", "items": {"type": "string"}},
        "designs": {"type": "array", "items": {"type": "string", "enum": list(STUDY_DESIGN_FILTERS)}},
    },
    "required": ["claim", "population", "intervention", "comparison", "outcome", "designs"],
    "additionalProperties": False,
}


class QuestionTranslationRejected(ValueError):
    pass


@dataclass(frozen=True)
class SearchDraft:
    claim: str
    population: tuple[str, ...]
    intervention: tuple[str, ...]
    comparison: tuple[str, ...]
    outcome: tuple[str, ...]
    designs: tuple[str, ...]
    model_id: str


def question_prompt() -> PromptTemplate:
    return PromptTemplate(PROMPT_ID, "Portuguese question to PICO", "Draft a PubMed search for physician review",
                          INSTRUCTIONS, ("CanonicalStructuredDTO",), "question-to-pico-output-v1", POLICY)


def _clean(values, limit=4) -> tuple[str, ...]:
    out = []
    for value in values or []:
        term = re.sub(r"\s+", " ", re.sub(r"[\"'\[\]()*]", "", str(value))).strip()[:80]
        if term and not re.search(r"\b(AND|OR|NOT)\b", term) and term.casefold() not in {t.casefold() for t in out}:
            out.append(term)
    return tuple(out[:limit])


class QuestionTranslationService:
    def __init__(self, gateway, *, prompt_version_id: str, model: LLMModel, clock: Callable[[], datetime]):
        self._gateway, self._prompt, self._model, self._clock = gateway, prompt_version_id, model, clock

    def translate(self, question_pt: str, context: str = "") -> SearchDraft:
        question = deidentify(" ".join((question_pt or "").split())).text
        context = deidentify(" ".join((context or "").split())).text
        if len(question) < 8 and len(context) < 8:
            raise QuestionTranslationRejected("Escreva a pergunta clínica ou escolha um modelo de cirurgia.")
        fields = [StructuredField("pergunta", question or "(ver contexto)", "physician-question")]
        if context:
            fields.append(StructuredField("contexto_procedimento_opme", context, "surgical-template"))
        dto = CanonicalStructuredDTO("question-to-pico-input", "1", tuple(fields), POLICY, ("physician-question",))
        response = self._gateway.invoke(LLMRequest(
            "pico-" + uuid4().hex, self._prompt, self._model, dto, ReviewPolicy("physician-search-review", POLICY, True, False),
            0.0, None, 2000, POLICY, self._clock()))
        if response.classification is LLMOutputClassification.BLOCKED:
            raise QuestionTranslationRejected("O modelo recusou a pergunta. Reformule.")
        try:
            match = re.search(r"\{.*\}", response.output_text, re.DOTALL)
            data = json.loads(match.group(0) if match else response.output_text)
        except (ValueError, AttributeError):
            raise QuestionTranslationRejected("Resposta do modelo fora do formato. Tente de novo.") from None
        draft = SearchDraft(" ".join(str(data.get("claim", "")).split())[:300], _clean(data.get("population")),
                            _clean(data.get("intervention")), _clean(data.get("comparison")), _clean(data.get("outcome")),
                            tuple(d for d in dict.fromkeys(data.get("designs") or []) if d in STUDY_DESIGN_FILTERS),
                            self._model.model_id)
        try:  # must be a valid, injection-free search before it reaches the page
            PICOQuestion(draft.population, draft.intervention, draft.comparison, draft.outcome, draft.designs)
        except EvidenceQueryRejected as exc:
            raise QuestionTranslationRejected("Não foi possível montar a busca. Reformule a pergunta.") from exc
        return draft
