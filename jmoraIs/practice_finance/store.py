"""Local SQLite store for surgeries, invoices and payments (file mode 0600)."""
from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import threading
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field

SCHEMA = """
CREATE TABLE IF NOT EXISTS surgeries(
  id TEXT PRIMARY KEY, date TEXT NOT NULL, hospital TEXT NOT NULL DEFAULT '', insurer TEXT NOT NULL DEFAULT '',
  patient TEXT NOT NULL DEFAULT '', card TEXT NOT NULL DEFAULT '', procedure TEXT NOT NULL DEFAULT '',
  codes TEXT NOT NULL DEFAULT '', role TEXT NOT NULL DEFAULT '', expected_cents INTEGER NOT NULL DEFAULT 0,
  guide TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '', invoice_id TEXT, source TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS invoices(
  id TEXT PRIMARY KEY, number TEXT NOT NULL, issue_date TEXT NOT NULL, hospital TEXT NOT NULL DEFAULT '',
  hospital_doc TEXT NOT NULL DEFAULT '', value_cents INTEGER NOT NULL, description TEXT NOT NULL DEFAULT '',
  source TEXT NOT NULL DEFAULT '', UNIQUE(number, hospital_doc));
CREATE TABLE IF NOT EXISTS payments(
  id TEXT PRIMARY KEY, date TEXT NOT NULL, payer TEXT NOT NULL DEFAULT '', value_cents INTEGER NOT NULL,
  reference TEXT NOT NULL DEFAULT '', description TEXT NOT NULL DEFAULT '', invoice_id TEXT,
  source TEXT NOT NULL DEFAULT '', fingerprint TEXT UNIQUE);
CREATE INDEX IF NOT EXISTS surgeries_date ON surgeries(date);
"""


class Surgery(BaseModel):
    id: str = ""
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    hospital: str = Field("", max_length=160)
    insurer: str = Field("", max_length=120)
    patient: str = Field("", max_length=160)
    card: str = Field("", max_length=60)
    procedure: str = Field("", max_length=300)
    codes: str = Field("", max_length=200)
    role: str = Field("", max_length=60)
    expected_cents: int = Field(0, ge=0, le=10**10)
    guide: str = Field("", max_length=60)
    notes: str = Field("", max_length=500)
    invoice_id: Optional[str] = None
    source: str = Field("", max_length=60)


class Invoice(BaseModel):
    id: str = ""
    number: str = Field(min_length=1, max_length=40)
    issue_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    hospital: str = Field("", max_length=200)
    hospital_doc: str = Field("", max_length=20)
    value_cents: int = Field(ge=0, le=10**11)
    description: str = Field("", max_length=4000)
    source: str = Field("", max_length=60)


class Payment(BaseModel):
    id: str = ""
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    payer: str = Field("", max_length=200)
    value_cents: int = Field(ge=0, le=10**11)
    reference: str = Field("", max_length=200)
    description: str = Field("", max_length=4000)
    invoice_id: Optional[str] = None
    source: str = Field("", max_length=60)


class FinanceStore:
    def __init__(self, path: Path):
        self._path = Path(path)
        self._lock = threading.Lock()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        new = not self._path.exists()
        with self._connect() as db:
            db.executescript(SCHEMA)
        if new:
            os.chmod(self._path, 0o600)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self._path)
        db.row_factory = sqlite3.Row
        return db

    # surgeries
    def surgeries(self, start: str = "", end: str = "") -> list[Surgery]:
        with self._connect() as db:
            rows = db.execute("SELECT * FROM surgeries WHERE (?='' OR date>=?) AND (?='' OR date<=?) ORDER BY date DESC, hospital",
                              (start, start, end, end)).fetchall()
        return [Surgery(**dict(r)) for r in rows]

    def save_surgery(self, s: Surgery) -> Surgery:
        s = s.model_copy(update={"id": s.id or "cir-" + uuid4().hex[:12]})
        fields = list(Surgery.model_fields)
        with self._lock, self._connect() as db:
            db.execute(f"INSERT OR REPLACE INTO surgeries({','.join(fields)}) VALUES({','.join('?' * len(fields))})",
                       [getattr(s, f) for f in fields])
        return s

    def delete_surgery(self, surgery_id: str) -> None:
        with self._lock, self._connect() as db:
            db.execute("DELETE FROM surgeries WHERE id=?", (surgery_id,))

    def link_surgery(self, surgery_id: str, invoice_id: Optional[str]) -> None:
        with self._lock, self._connect() as db:
            db.execute("UPDATE surgeries SET invoice_id=? WHERE id=?", (invoice_id, surgery_id))

    # invoices
    def invoices(self) -> list[Invoice]:
        with self._connect() as db:
            return [Invoice(**dict(r)) for r in db.execute("SELECT * FROM invoices ORDER BY issue_date DESC").fetchall()]

    def save_invoice(self, inv: Invoice) -> tuple[Invoice, bool]:
        """Insert unless the same number from the same hospital already exists; returns (invoice, created)."""
        with self._lock, self._connect() as db:
            row = db.execute("SELECT * FROM invoices WHERE number=? AND hospital_doc=?", (inv.number, inv.hospital_doc)).fetchone()
            if row is not None and not inv.id:
                return Invoice(**dict(row)), False
            inv = inv.model_copy(update={"id": inv.id or "nf-" + uuid4().hex[:12]})
            fields = list(Invoice.model_fields)
            db.execute(f"INSERT OR REPLACE INTO invoices({','.join(fields)}) VALUES({','.join('?' * len(fields))})",
                       [getattr(inv, f) for f in fields])
        return inv, True

    def delete_invoice(self, invoice_id: str) -> None:
        with self._lock, self._connect() as db:
            db.execute("UPDATE surgeries SET invoice_id=NULL WHERE invoice_id=?", (invoice_id,))
            db.execute("UPDATE payments SET invoice_id=NULL WHERE invoice_id=?", (invoice_id,))
            db.execute("DELETE FROM invoices WHERE id=?", (invoice_id,))

    # payments
    def payments(self) -> list[Payment]:
        with self._connect() as db:
            return [Payment(**{k: r[k] for k in Payment.model_fields}) for r in
                    db.execute("SELECT * FROM payments ORDER BY date DESC").fetchall()]

    def save_payment(self, p: Payment) -> tuple[Payment, bool]:
        fingerprint = f"{p.date}|{p.value_cents}|{p.payer.casefold()}|{p.reference.casefold()}"
        with self._lock, self._connect() as db:
            row = db.execute("SELECT id FROM payments WHERE fingerprint=?", (fingerprint,)).fetchone()
            if row is not None and not p.id:
                return p.model_copy(update={"id": row["id"]}), False
            p = p.model_copy(update={"id": p.id or "pg-" + uuid4().hex[:12]})
            fields = list(Payment.model_fields)
            db.execute(f"INSERT OR REPLACE INTO payments({','.join(fields)},fingerprint) VALUES({','.join('?' * (len(fields) + 1))})",
                       [getattr(p, f) for f in fields] + [fingerprint])
        return p, True

    def link_payment(self, payment_id: str, invoice_id: Optional[str]) -> None:
        with self._lock, self._connect() as db:
            db.execute("UPDATE payments SET invoice_id=? WHERE id=?", (invoice_id, payment_id))

    def delete_payment(self, payment_id: str) -> None:
        with self._lock, self._connect() as db:
            db.execute("DELETE FROM payments WHERE id=?", (payment_id,))
