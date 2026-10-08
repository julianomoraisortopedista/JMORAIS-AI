"""Contestation of an insurer denial, glosa or medical-board opinion, drafted point by point.

Sources the model may cite (and nothing else): the denial's own sentences (N1..), the
physician-confirmed clinical facts (F1..), the procedure context (CTX), the SBOT coding
manual entry (SBOT) and fixed legal texts (L ids: verbatim official excerpts, plus a few
norms transcribed from the SBOT practical guide, labelled as such). Every sentence must
cite valid ids and every number it contains must appear in the cited sources, so norm
numbers, scores and dates cannot be invented. The physician's past contestations that
were granted are passed as format and argument EXAMPLES only; they are never a source.
De-identified input only; the result is a draft for the physician to review and sign.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import re
from typing import Callable
from uuid import uuid4

from jmoraIs.application.legal_basis import LEGAL_SOURCES
from jmoraIs.llm_gateway.domain import (
    CanonicalStructuredDTO, LLMModel, LLMOutputClassification, LLMRequest, PromptTemplate, ReviewPolicy, StructuredField,
)

POLICY = "MIP-10.1"
PROMPT_ID = "insurer-contestation-v1"
SECTIONS = (
    ("sintese", "Síntese da negativa"),
    ("clinico", "Fundamentos clínicos"),
    ("tecnico", "Fundamentos técnicos e de codificação"),
    ("normativo", "Fundamentos normativos"),
    ("pedido", "Pedido"),
)
KIND_PT = {"NEGATIVA": "negativa de autorização", "GLOSA": "glosa", "JUNTA_MEDICA": "parecer de junta médica"}
GUIDE = "transcrição do Guia Prático SBOT para Médicos Ortopedistas (2025); conferir texto oficial"
SECONDARY_SOURCES = {  # norms not fetched from the official site: citation carries the provenance
    "L-RN503-ART5-VI": ("RN ANS nº 503/2022, art. 5º, VI (" + GUIDE + ")",
                        "São vedadas na contratualização entre Operadoras e Prestadores as práticas de estabelecer "
                        "quaisquer regras que impeçam o Prestador de contestar as glosas."),
    "L-RN424": ("RN ANS nº 424/2017, ementa (" + GUIDE + ")",
                "Dispõe sobre critérios para a realização de junta médica ou odontológica formada para dirimir "
                "divergência técnico-assistencial sobre procedimento ou evento em saúde a ser coberto pelas operadoras."),
    "L-RN566-ART3-XIII": ("RN ANS nº 566/2022, art. 3º, XIII (" + GUIDE + ")",
                          "Atendimento em regime de internação eletiva: em até 21 (vinte e um) dias úteis."),
}
INSTRUCTIONS = (
    "Você é um ortopedista sênior redigindo a contestação de uma {kind} enviada por uma operadora de plano de "
    "saúde. Escreva em português formal, técnico e respeitoso, em primeira pessoa do médico assistente. Responda "
    "a cada argumento da operadora (N1, N2...) com fatos clínicos confirmados (F...), o contexto do procedimento "
    "(CTX), o Manual de Codificação da SBOT (SBOT) e os textos normativos fornecidos (L-...). Cada frase deve citar "
    "os ids que a sustentam. Não invente fatos, números, escalas, datas, artigos, leis, resoluções ou "
    "jurisprudência: cite só o que foi fornecido, pelo id. Se faltar dado para rebater um argumento, diga isso em "
    "'gaps'. Os EXEMPLOS são contestações anteriores do próprio médico que deram certo: use como modelo de "
    "estrutura, tom e linha de argumentação, nunca como fonte, e nunca copie dados deles. Em 'pedido', peça a "
    "reconsideração e, se cabível, a junta médica. Responda somente com o JSON solicitado."
)
OUTPUT_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "sections": {"type": "array", "items": {"type": "object", "properties": {
            "section": {"type": "string", "enum": [k for k, _ in SECTIONS]},
            "sentences": {"type": "array", "items": {"type": "object", "properties": {
                "text": {"type": "string"}, "source_ids": {"type": "array", "items": {"type": "string"}}},
                "required": ["text", "source_ids"], "additionalProperties": False}}},
            "required": ["section", "sentences"], "additionalProperties": False}},
        "gaps": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["sections", "gaps"],
    "additionalProperties": False,
}
_NUMBER = re.compile(r"\d+")  # digit runs: "9.656" and "8,5" are compared part by part


class AppealDraftRejected(ValueError):
    pass


@dataclass(frozen=True)
class AppealSentence:
    text: str
    source_ids: tuple[str, ...]


@dataclass(frozen=True)
class AppealDraft:
    sections: tuple[tuple[str, str, tuple[AppealSentence, ...]], ...]
    gaps: tuple[str, ...]
    dropped: int
    sources: dict          # id -> label shown to the physician
    model_id: str


def appeal_prompt() -> PromptTemplate:
    return PromptTemplate(PROMPT_ID, "Insurer contestation", "Draft a point-by-point contestation for physician review",
                          INSTRUCTIONS.format(kind="negativa, glosa ou parecer de junta médica"),
                          ("CanonicalStructuredDTO",), "insurer-contestation-output-v1", POLICY)


def denial_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.;!?])\s+|\n+", " ".join((text or "").replace("\r", "").split(" ")))
    return [" ".join(p.split()) for p in parts if len(p.split()) >= 3][:40]


def _numbers(text: str) -> set[str]:
    return set(_NUMBER.findall(text or ""))


def legal_sources() -> dict[str, tuple[str, str]]:
    sources = {"L-" + k.upper(): (s.citation, s.excerpt) for k, s in LEGAL_SOURCES.items()}
    sources.update(SECONDARY_SOURCES)
    return sources


class AppealDraftingService:
    def __init__(self, gateway, *, prompt_version_id: str, model: LLMModel, clock: Callable[[], datetime]):
        self._gateway, self._prompt, self._model, self._clock = gateway, prompt_version_id, model, clock

    def draft(self, *, kind: str, denial_text: str, facts: list[dict], context: str, sbot: str,
              examples: list[str]) -> AppealDraft:
        denial = denial_sentences(denial_text)
        if not denial:
            raise AppealDraftRejected("Cole ou anexe o texto da negativa da operadora.")
        support: dict[str, str] = {}
        labels: dict[str, str] = {}
        fields = [StructuredField("TIPO", KIND_PT.get(kind, kind), "physician-request")]
        for n, sentence in enumerate(denial, 1):
            support[f"N{n}"] = sentence
            labels[f"N{n}"] = "Negativa: " + sentence[:120]
            fields.append(StructuredField(f"N{n}", sentence, "insurer-denial"))
        for n, fact in enumerate(facts, 1):
            support[f"F{n}"] = f"{fact['statement']} {fact['quote']}"
            labels[f"F{n}"] = f"{fact['statement']} ({fact.get('source', 'fato confirmado')})"
            fields.append(StructuredField(f"F{n}", f"[{fact['category_label']}] {fact['statement']} (fonte: “{fact['quote']}”)",
                                          "confirmed-fact"))
        if context.strip():
            support["CTX"], labels["CTX"] = context, "Procedimento solicitado"
            fields.append(StructuredField("CTX", context, "physician-request"))
        if sbot.strip():
            support["SBOT"], labels["SBOT"] = sbot, "Manual de Codificação SBOT"
            fields.append(StructuredField("SBOT", sbot, "sbot-coding-manual"))
        for sid, (citation, excerpt) in legal_sources().items():
            support[sid], labels[sid] = f"{citation} {excerpt}", citation
            fields.append(StructuredField(sid, f"{citation}: “{excerpt}”", "legal-text"))
        for n, example in enumerate(examples[:2], 1):
            fields.append(StructuredField(f"EXEMPLO{n}", example[:6000], "physician-past-contestation"))
        dto = CanonicalStructuredDTO("insurer-contestation-input", "1", tuple(fields), POLICY, ("insurer-denial",))
        response = self._gateway.invoke(LLMRequest(
            "appeal-" + uuid4().hex, self._prompt, self._model, dto, ReviewPolicy("physician-appeal-review", POLICY, True, False),
            0.0, None, 8000, POLICY, self._clock()))
        if response.classification is LLMOutputClassification.BLOCKED:
            raise AppealDraftRejected("O modelo recusou a redação.")
        try:
            match = re.search(r"\{.*\}", response.output_text, re.DOTALL)
            data = json.loads(match.group(0) if match else response.output_text)
        except (ValueError, AttributeError):
            raise AppealDraftRejected("Resposta do modelo fora do formato. Tente de novo.") from None
        by_key: dict[str, list[AppealSentence]] = {k: [] for k, _ in SECTIONS}
        dropped = 0
        for section in data.get("sections") or []:
            key = section.get("section")
            if key not in by_key:
                continue
            for sentence in section.get("sentences") or []:
                text = " ".join(str(sentence.get("text", "")).split())[:900]
                cited = tuple(dict.fromkeys(str(i).strip().upper() for i in sentence.get("source_ids") or []))
                valid = bool(text and cited and all(i in support for i in cited))
                allowed = set().union(*(_numbers(support[i]) for i in cited)) if valid else set()
                if not valid or not _numbers(text) <= allowed:
                    dropped += 1
                    continue
                by_key[key].append(AppealSentence(text, cited))
        used = {i for ss in by_key.values() for s in ss for i in s.source_ids}
        gaps = tuple(" ".join(str(g).split())[:300] for g in data.get("gaps") or [] if str(g).strip())[:12]
        return AppealDraft(tuple((k, t, tuple(by_key[k])) for k, t in SECTIONS), gaps, dropped,
                           {i: labels[i] for i in sorted(used)}, self._model.model_id)
