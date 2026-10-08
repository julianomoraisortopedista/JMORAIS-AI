"""Matching surgeries -> invoices -> payments, statuses, alerts and the monthly panel.

Suggestions only: a link is written when the evidence is unambiguous (patient named in the
invoice description, invoice number cited in the payment, or exact value from the same
payer); everything else stays as a suggestion for the physician to confirm.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
import re

from jmoraIs.practice_finance.importers import fold
from jmoraIs.practice_finance.store import FinanceStore, Invoice, Payment, Surgery

def brl(cents: int) -> str:
    whole, frac = divmod(abs(cents), 100)
    return ("-" if cents < 0 else "") + "R$ " + f"{whole:,}".replace(",", ".") + f",{frac:02d}"


def br(iso: str) -> str:
    return "/".join(reversed(iso.split("-"))) if iso else ""


STOP = {"hospital", "ltda", "s/a", "sa", "de", "da", "do", "das", "dos", "e", "me", "eireli", "clinica", "sociedade", "beneficente"}


@dataclass(frozen=True)
class Suggestion:
    kind: str          # SURGERY_INVOICE / PAYMENT_INVOICE
    left_id: str
    invoice_id: str
    reason: str
    certain: bool


def _words(name: str) -> set[str]:
    return {w for w in re.split(r"[^a-z0-9]+", fold(name)) if len(w) >= 3 and w not in STOP}


def same_payer(a: str, b: str) -> bool:
    wa, wb = _words(a), _words(b)
    return bool(wa and wb and (wa & wb))


def _patient_in(patient: str, text: str) -> bool:
    words = [w for w in re.split(r"\s+", fold(patient)) if len(w) >= 3 and w not in STOP]
    folded = fold(text)
    return len(words) >= 2 and all(re.search(r"(?<!\w)" + re.escape(w) + r"(?!\w)", folded) for w in words[:3])


def suggest(store: FinanceStore) -> list[Suggestion]:
    surgeries, invoices, payments = store.surgeries(), store.invoices(), store.payments()
    out: list[Suggestion] = []
    for s in surgeries:
        if s.invoice_id:
            continue
        sdate = date.fromisoformat(s.date)
        candidates = [i for i in invoices if (not s.hospital or not i.hospital or same_payer(s.hospital, i.hospital))
                      and sdate <= date.fromisoformat(i.issue_date) <= sdate + timedelta(days=120)]
        named = [i for i in candidates if s.patient and _patient_in(s.patient, i.description)]
        if len(named) == 1:
            out.append(Suggestion("SURGERY_INVOICE", s.id, named[0].id, "paciente citado na discriminação da nota", True))
        elif s.expected_cents:
            exact = [i for i in candidates if i.value_cents == s.expected_cents]
            if len(exact) == 1:
                out.append(Suggestion("SURGERY_INVOICE", s.id, exact[0].id, "mesmo hospital e mesmo valor", False))
    numbers = {i.number: i for i in invoices}
    for p in payments:
        if p.invoice_id:
            continue
        cited = [numbers[n.lstrip("0")] for n in re.findall(r"\d+", p.reference) if n.lstrip("0") in numbers]
        if len(cited) == 1:
            out.append(Suggestion("PAYMENT_INVOICE", p.id, cited[0].id, f"NF {cited[0].number} citada no pagamento", True))
            continue
        exact = [i for i in invoices if i.value_cents == p.value_cents and same_payer(p.payer, i.hospital)
                 and i.issue_date <= p.date]
        if len(exact) == 1:
            out.append(Suggestion("PAYMENT_INVOICE", p.id, exact[0].id, "mesmo pagador e mesmo valor", False))
    return out


def apply_certain(store: FinanceStore) -> int:
    applied = 0
    for s in suggest(store):
        if s.certain:
            (store.link_surgery if s.kind == "SURGERY_INVOICE" else store.link_payment)(s.left_id, s.invoice_id)
            applied += 1
    return applied


def surgery_status(s: Surgery, invoices: dict[str, Invoice], paid_by_invoice: dict[str, int]) -> str:
    if not s.invoice_id or s.invoice_id not in invoices:
        return "REALIZADA"
    inv = invoices[s.invoice_id]
    paid = paid_by_invoice.get(inv.id, 0)
    if paid == 0:
        return "FATURADA"
    return "PAGA" if paid >= inv.value_cents else "PAGA_PARCIAL"


def panel(store: FinanceStore, today: date, invoice_due_days: int = 30, payment_due_days: int = 45) -> dict:
    surgeries, invoices, payments = store.surgeries(), store.invoices(), store.payments()
    by_id = {i.id: i for i in invoices}
    paid: dict[str, int] = defaultdict(int)
    for p in payments:
        if p.invoice_id:
            paid[p.invoice_id] += p.value_cents
    months: dict[tuple[str, str], dict] = defaultdict(lambda: dict(cirurgias=0, previsto=0, faturado=0, recebido=0))
    for s in surgeries:
        row = months[(s.date[:7], s.hospital or "—")]
        row["cirurgias"] += 1
        row["previsto"] += s.expected_cents
    for i in invoices:
        row = months[(i.issue_date[:7], i.hospital or "—")]
        row["faturado"] += i.value_cents
    for p in payments:
        row = months[(p.date[:7], (by_id[p.invoice_id].hospital if p.invoice_id in by_id else p.payer) or "—")]
        row["recebido"] += p.value_cents
    alerts = []
    for s in surgeries:
        if not s.invoice_id and (today - date.fromisoformat(s.date)).days > invoice_due_days:
            alerts.append(dict(level="ATENCAO", kind="SEM_NOTA", ref=s.id,
                               message=f"Cirurgia de {br(s.date)} ({s.procedure or 'procedimento'}, {s.hospital}) sem nota fiscal há mais de {invoice_due_days} dias."))
    for i in invoices:
        received = paid.get(i.id, 0)
        late = (today - date.fromisoformat(i.issue_date)).days > payment_due_days
        if received == 0 and late:
            alerts.append(dict(level="ATENCAO", kind="SEM_PAGAMENTO", ref=i.id,
                               message=f"NF {i.number} ({i.hospital}) de {br(i.issue_date)} sem pagamento há mais de {payment_due_days} dias."))
        elif 0 < received < i.value_cents:
            alerts.append(dict(level="BLOQUEIO", kind="PAGO_A_MENOR", ref=i.id,
                               message=f"NF {i.number} ({i.hospital}): recebido {brl(received)} de {brl(i.value_cents)}; "
                                       f"diferença {brl(i.value_cents - received)} (possível glosa)."))
    for p in payments:
        if not p.invoice_id:
            alerts.append(dict(level="INFO", kind="PAGAMENTO_SEM_NOTA", ref=p.id,
                               message=f"Pagamento de {br(p.date)} ({p.payer}, {brl(p.value_cents)}) sem nota vinculada."))
    statuses = {s.id: surgery_status(s, by_id, paid) for s in surgeries}
    totals = dict(cirurgias=len(surgeries), previsto=sum(s.expected_cents for s in surgeries),
                  faturado=sum(i.value_cents for i in invoices), recebido=sum(p.value_cents for p in payments),
                  a_faturar=sum(s.expected_cents for s in surgeries if not s.invoice_id),
                  a_receber=sum(max(i.value_cents - paid.get(i.id, 0), 0) for i in invoices))
    return {"totals": totals, "statuses": statuses,
            "months": [dict(month=m, hospital=h, **v) for (m, h), v in sorted(months.items(), reverse=True)],
            "alerts": alerts}
