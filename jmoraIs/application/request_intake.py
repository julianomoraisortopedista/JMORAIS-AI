"""Physician's spoken or typed request -> structured surgery request and scheduling.

E.g. "ATJ direita, Zimmer, Hospital Santa Cruz, dia 20/10 às 7h, raqui, reserva de UTI".
The text is de-identified first; the model may only pick a surgery template and a
supplier that exist in the catalog, and dates/times are validated. The page fills the
form with the result and the physician confirms every field; nothing is a clinical fact.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import json
import re
from typing import Callable, Optional
from uuid import uuid4

from jmoraIs.application.deidentification import deidentify
from jmoraIs.llm_gateway.domain import (
    CanonicalStructuredDTO, LLMModel, LLMOutputClassification, LLMRequest, PromptTemplate, ReviewPolicy, StructuredField,
)

POLICY = "MIP-10.1"
PROMPT_ID = "surgery-request-intake-v1"
LATERALITY = ("", "Direito", "Esquerdo", "Bilateral")
REGIMES = ("", "Internação", "Ambulatorial", "Hospital-dia")
INSTRUCTIONS = (
    "Você recebe o pedido de um ortopedista, ditado ou digitado, para solicitar uma cirurgia ao convênio e "
    "agendá-la no hospital. Preencha o JSON: template_id (escolha entre os MODELOS listados o que corresponde "
    "ao procedimento pedido; vazio se nenhum corresponder), procedure (o procedimento como o médico disse), "
    "laterality, supplier (um dos FORNECEDORES listados, se o médico citar; senão vazio), hospital, date "
    "(AAAA-MM-DD; use HOJE para resolver 'amanhã', 'dia 20' etc.; vazio se não dito), time (HH:MM, 24 h), "
    "duration_minutes (0 se não dito), regime, anesthesia, icu (true/false/null), blood_reserve (true/false/null) "
    "e notes (outros pedidos ao hospital). Não invente nada que o médico não disse. Responda só com o JSON."
)
OUTPUT_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "template_id": {"type": "string"}, "procedure": {"type": "string"},
        "laterality": {"type": "string", "enum": list(LATERALITY)}, "supplier": {"type": "string"},
        "hospital": {"type": "string"}, "date": {"type": "string"}, "time": {"type": "string"},
        "duration_minutes": {"type": "integer"}, "regime": {"type": "string", "enum": list(REGIMES)},
        "anesthesia": {"type": "string"},
        "icu": {"anyOf": [{"type": "boolean"}, {"type": "null"}]},
        "blood_reserve": {"anyOf": [{"type": "boolean"}, {"type": "null"}]},
        "notes": {"type": "string"},
    },
    "required": ["template_id", "procedure", "laterality", "supplier", "hospital", "date", "time", "duration_minutes",
                 "regime", "anesthesia", "icu", "blood_reserve", "notes"],
    "additionalProperties": False,
}


class RequestIntakeRejected(ValueError):
    pass


@dataclass(frozen=True)
class SurgeryRequestDraft:
    template_id: str
    procedure: str
    laterality: str
    supplier: str
    hospital: str
    date: str
    time: str
    duration_minutes: int
    regime: str
    anesthesia: str
    icu: Optional[bool]
    blood_reserve: Optional[bool]
    notes: str
    model_id: str


def request_prompt() -> PromptTemplate:
    return PromptTemplate(PROMPT_ID, "Surgery request intake", "Structure a dictated surgery request for physician review",
                          INSTRUCTIONS, ("CanonicalStructuredDTO",), "surgery-request-output-v1", POLICY)


def _text(value, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _date(value: str, today: date) -> str:
    try:
        parsed = date.fromisoformat(str(value or "").strip())
    except ValueError:
        return ""
    return parsed.isoformat() if today <= parsed <= today + timedelta(days=731) else ""


def _time(value: str) -> str:
    m = re.fullmatch(r"([01]?\d|2[0-3])[:h]([0-5]\d)?", str(value or "").strip())
    return f"{int(m.group(1)):02d}:{m.group(2) or '00'}" if m else ""


class RequestIntakeService:
    def __init__(self, gateway, *, prompt_version_id: str, model: LLMModel, clock: Callable[[], datetime]):
        self._gateway, self._prompt, self._model, self._clock = gateway, prompt_version_id, model, clock

    def parse(self, text: str, templates: list[tuple[str, str]], suppliers: list[str]) -> SurgeryRequestDraft:
        spoken = deidentify(_text(text, 2000)).text
        if len(spoken) < 6:
            raise RequestIntakeRejected("Diga ou escreva o procedimento que quer solicitar.")
        today = self._clock().date()
        fields = [StructuredField("pedido", spoken, "physician-request"),
                  StructuredField("HOJE", today.isoformat(), "clock"),
                  StructuredField("MODELOS", "; ".join(f"{i} = {n}" for i, n in templates) or "(nenhum)", "catalog"),
                  StructuredField("FORNECEDORES", "; ".join(suppliers) or "(nenhum)", "catalog")]
        dto = CanonicalStructuredDTO("surgery-request-input", "1", tuple(fields), POLICY, ("physician-request",))
        response = self._gateway.invoke(LLMRequest(
            "request-" + uuid4().hex, self._prompt, self._model, dto, ReviewPolicy("physician-request-review", POLICY, True, False),
            0.0, None, 1500, POLICY, self._clock()))
        if response.classification is LLMOutputClassification.BLOCKED:
            raise RequestIntakeRejected("O modelo recusou o pedido. Reformule.")
        try:
            match = re.search(r"\{.*\}", response.output_text, re.DOTALL)
            data = json.loads(match.group(0) if match else response.output_text)
        except (ValueError, AttributeError):
            raise RequestIntakeRejected("Resposta do modelo fora do formato. Tente de novo.") from None
        ids = {i for i, _ in templates}
        supplier = _text(data.get("supplier"), 120)
        boolean = lambda v: v if isinstance(v, bool) else None  # noqa: E731
        try:
            duration = int(data.get("duration_minutes") or 0)
        except (TypeError, ValueError):
            duration = 0
        return SurgeryRequestDraft(
            template_id=data.get("template_id") if data.get("template_id") in ids else "",
            procedure=_text(data.get("procedure"), 300),
            laterality=data.get("laterality") if data.get("laterality") in LATERALITY else "",
            supplier=supplier if supplier in suppliers else "",
            hospital=_text(data.get("hospital"), 160), date=_date(data.get("date"), today), time=_time(data.get("time")),
            duration_minutes=duration if 0 < duration <= 1440 else 0,
            regime=data.get("regime") if data.get("regime") in REGIMES else "",
            anesthesia=_text(data.get("anesthesia"), 120), icu=boolean(data.get("icu")),
            blood_reserve=boolean(data.get("blood_reserve")), notes=_text(data.get("notes"), 500),
            model_id=self._model.model_id)
