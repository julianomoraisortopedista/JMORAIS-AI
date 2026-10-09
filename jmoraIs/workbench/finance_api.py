"""HTTP routes of the practice-finance domain (surgeries, invoices, payments), mounted by create_app."""
from __future__ import annotations

import base64
from datetime import datetime
from typing import Callable, Optional

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from jmoraIs.practice_finance.importers import (
    ImportRejected, invoice_from_text, invoices_from_xml, payments_from_table, payments_from_text, read_email, read_table,
    surgeries_from_table, surgeries_from_workbook,
)
from jmoraIs.practice_finance.reconcile import apply_certain, panel, suggest
from jmoraIs.practice_finance.store import FinanceStore, Surgery

MAX_FILE_B64 = 1_000_000 - 4096


class FileIn(BaseModel):
    name: str = Field(max_length=200)
    content_base64: str = Field(max_length=MAX_FILE_B64)


class SurgeryImportIn(FileIn):
    mapping: Optional[dict[str, int]] = None
    commit: bool = False


class PaymentImportIn(FileIn):
    payer: str = Field("", max_length=200)


class LinkIn(BaseModel):
    kind: str = Field(pattern="^(SURGERY_INVOICE|PAYMENT_INVOICE)$")
    left_id: str = Field(max_length=40)
    invoice_id: Optional[str] = Field(None, max_length=40)


def _bad(detail: str, status: int = 400):
    raise HTTPException(status, detail)


def _decode(body: FileIn) -> bytes:
    try:
        return base64.b64decode(body.content_base64, validate=True)
    except ValueError:
        _bad("Arquivo inválido.")


def _pdf_text(content: bytes) -> str:
    from jmoraIs.application.case_intake import CaseIntakeRejected, extract_text
    try:
        return extract_text("x.pdf", content)
    except CaseIntakeRejected as exc:
        raise ImportRejected(str(exc)) from exc


def mount_finance(app: FastAPI, store: FinanceStore, clock: Callable[[], datetime]) -> None:
    @app.get("/api/finance/panel")
    def finance_panel():
        return panel(store, clock().date())

    @app.get("/api/finance/surgeries")
    def finance_surgeries(start: str = Query("", max_length=10), end: str = Query("", max_length=10)):
        return {"surgeries": [s.model_dump() for s in store.surgeries(start, end)]}

    @app.put("/api/finance/surgeries")
    def finance_surgery_save(body: Surgery):
        return store.save_surgery(body).model_dump()

    @app.delete("/api/finance/surgeries/{surgery_id}")
    def finance_surgery_delete(surgery_id: str):
        store.delete_surgery(surgery_id)
        return {"deleted": surgery_id}

    @app.post("/api/finance/import/surgeries")
    def finance_import_surgeries(body: SurgeryImportIn):
        try:
            content = _decode(body)
            if body.name.lower().endswith(".xlsx"):
                surgeries, skipped, info = surgeries_from_workbook(content, body.mapping)
            else:
                surgeries, skipped, info = surgeries_from_table(read_table(body.name, content), body.mapping)
        except ImportRejected as exc:
            _bad(str(exc))
        if not body.commit:
            return {"preview": [s.model_dump() for s in surgeries[:15]], "count": len(surgeries), "skipped": skipped[:30], **info}
        existing = {(s.date, s.patient.casefold(), s.procedure.casefold()) for s in store.surgeries()}
        added = 0
        for s in surgeries:
            key = (s.date, s.patient.casefold(), s.procedure.casefold())
            if key not in existing:
                store.save_surgery(s)
                existing.add(key)
                added += 1
        return {"added": added, "duplicates": len(surgeries) - added, "skipped": skipped[:30], "linked": apply_certain(store)}

    @app.get("/api/finance/invoices")
    def finance_invoices():
        return {"invoices": [i.model_dump() for i in store.invoices()]}

    @app.post("/api/finance/import/invoices")
    def finance_import_invoices(body: FileIn):
        content, name = _decode(body), body.name.lower()
        try:
            if name.endswith(".xml"):
                invoices = invoices_from_xml(content)
            elif name.endswith(".pdf"):
                invoices = [invoice_from_text(_pdf_text(content))]
            else:
                _bad("Envie o XML da NFS-e (preferível) ou o PDF da nota.")
        except ImportRejected as exc:
            _bad(str(exc))
        created = [store.save_invoice(i) for i in invoices]
        return {"added": sum(1 for _, new in created if new), "duplicates": sum(1 for _, new in created if not new),
                "invoices": [i.model_dump() for i, _ in created], "linked": apply_certain(store)}

    @app.delete("/api/finance/invoices/{invoice_id}")
    def finance_invoice_delete(invoice_id: str):
        store.delete_invoice(invoice_id)
        return {"deleted": invoice_id}

    @app.get("/api/finance/payments")
    def finance_payments():
        return {"payments": [p.model_dump() for p in store.payments()]}

    @app.post("/api/finance/import/payments")
    def finance_import_payments(body: PaymentImportIn):
        content, name = _decode(body), body.name.lower()
        today = clock().date().isoformat()
        try:
            if name.endswith(".eml"):
                mail = read_email(content)
                payer = body.payer or mail["sender"]
                found = payments_from_text(mail["subject"] + "\n" + mail["text"], payer, mail["date"] or today, "email")
                for att_name, data in mail["attachments"]:
                    lower = att_name.lower()
                    if lower.endswith((".xlsx", ".csv")):
                        found += payments_from_table(read_table(lower, data), payer, "email-anexo")
                    elif lower.endswith(".pdf"):
                        found += payments_from_text(_pdf_text(data), payer, mail["date"] or today, "email-anexo")
            elif name.endswith((".xlsx", ".csv")):
                found = payments_from_table(read_table(name, content), body.payer, "demonstrativo")
            elif name.endswith(".pdf"):
                found = payments_from_text(_pdf_text(content), body.payer, today, "demonstrativo")
            else:
                _bad("Envie o e-mail (.eml) ou o demonstrativo (PDF, .xlsx, .csv).")
        except ImportRejected as exc:
            _bad(str(exc))
        if not found:
            _bad("Não encontrei valores (R$) neste arquivo.")
        created = [store.save_payment(p) for p in found]
        return {"added": sum(1 for _, new in created if new), "duplicates": sum(1 for _, new in created if not new),
                "payments": [p.model_dump() for p, _ in created], "linked": apply_certain(store)}

    @app.delete("/api/finance/payments/{payment_id}")
    def finance_payment_delete(payment_id: str):
        store.delete_payment(payment_id)
        return {"deleted": payment_id}

    @app.get("/api/finance/suggestions")
    def finance_suggestions():
        return {"suggestions": [s.__dict__ for s in suggest(store)]}

    @app.post("/api/finance/link")
    def finance_link(body: LinkIn):
        if body.invoice_id and body.invoice_id not in {i.id for i in store.invoices()}:
            _bad("Nota não encontrada.", 404)
        (store.link_surgery if body.kind == "SURGERY_INVOICE" else store.link_payment)(body.left_id, body.invoice_id)
        return {"ok": True}

