"""Maximum care deadlines (RN ANS nº 566/2022, art. 3º) for the request being prepared.

Text of the items as transcribed in the SBOT practical guide for orthopedists (2025) and
consistent with ANS communications; the official text could not be fetched from this
computer, so the citation carries that provenance. Business days skip weekends only:
holidays are not known here, so the date is an estimate the physician should confirm.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

SOURCE = "RN ANS nº 566/2022, art. 3º (transcrição do Guia Prático SBOT 2025; conferir texto oficial)"
RULES = {  # (regime, urgency) key -> (business days or 0 for immediate, item, description)
    "URGENCIA": (0, "XVII", "urgência e emergência: imediato"),
    "Internação": (21, "XIII", "atendimento em regime de internação eletiva: em até 21 dias úteis"),
    "Hospital-dia": (10, "XIV", "atendimento em regime de hospital-dia: em até 10 dias úteis"),
    "Ambulatorial": (10, "XI", "demais serviços de diagnóstico e terapia em regime ambulatorial: em até 10 dias úteis"),
}


@dataclass(frozen=True)
class Deadline:
    business_days: int
    item: str
    rule: str
    due: date | None
    citation: str = SOURCE

    def text(self) -> str:
        when = "imediato" if self.business_days == 0 else (
            f"até {self.due.strftime('%d/%m/%Y')} ({self.business_days} dias úteis, sem contar feriados)")
        return f"Prazo máximo de atendimento pela operadora: {when}. {self.citation}, inciso {self.item}: {self.rule}."


def add_business_days(start: date, days: int) -> date:
    current, added = start, 0
    while added < days:
        current += timedelta(days=1)
        if current.weekday() < 5:
            added += 1
    return current


def deadline_for(regime: str, urgency: str, requested_on: date) -> Deadline | None:
    key = "URGENCIA" if urgency in ("URGENCIA", "EMERGENCIA") else regime
    if key not in RULES:
        return None
    days, item, rule = RULES[key]
    return Deadline(days, item, rule, add_business_days(requested_on, days) if days else None)
