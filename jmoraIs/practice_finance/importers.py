"""Readers for the physician's spreadsheet, NFS-e invoices and payment e-mails/statements.

Deterministic parsing only (stdlib + pypdf). Everything read is returned for review before
it is saved; nothing is inferred beyond what the file states.
"""
from __future__ import annotations

import csv
from datetime import date, timedelta
from email import policy
from email.parser import BytesParser
import io
import re
import unicodedata
from xml.etree.ElementTree import fromstring

from jmoraIs.practice_finance.store import Invoice, Payment, Surgery


class ImportRejected(ValueError):
    pass


def fold(value: str) -> str:
    return " ".join("".join(c for c in unicodedata.normalize("NFKD", value or "") if not unicodedata.combining(c)).casefold().split())


# ---------- values ----------
def parse_money(value) -> int:
    """'R$ 1.234,56' / '1234.56' / '1234,5' / 1234.5 -> cents."""
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return round(float(value) * 100)
    text = re.sub(r"[^\d,.\-]", "", str(value))
    if not text or not re.search(r"\d", text):
        return 0
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".") if text.rfind(",") > text.rfind(".") else text.replace(",", "")
    elif "," in text:
        text = text.replace(".", "").replace(",", ".")
    elif text.count(".") > 1:
        text = text.replace(".", "")
    try:
        return round(float(text) * 100)
    except ValueError:
        return 0


def parse_date(value) -> str:
    """dd/mm/aaaa, aaaa-mm-dd, dd-mm-aa or an Excel serial -> ISO date ('' if unknown)."""
    text = str(value or "").strip()
    if re.fullmatch(r"\d{5}(\.\d+)?", text):  # Excel serial day
        return (date(1899, 12, 30) + timedelta(days=int(float(text)))).isoformat()
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.search(r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})", text)
    if m:
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        year = year + 2000 if year < 100 else year
        try:
            return date(year, month, day).isoformat()
        except ValueError:
            return ""
    return ""


# ---------- surgeries spreadsheet ----------
COLUMN_SYNONYMS = {  # field -> header words (folded)
    "date": ("data da cirurgia", "data cirurgia", "data do procedimento", "data"),
    "hospital": ("hospital", "local", "instituicao"),
    "insurer": ("convenio", "operadora", "plano"),
    "patient": ("paciente", "nome do paciente", "nome"),
    "card": ("carteirinha", "carteira", "matricula", "atendimento"),
    "procedure": ("procedimento", "cirurgia", "descricao"),
    "codes": ("tuss", "codigo", "codigos", "cbhpm"),
    "role": ("funcao", "papel", "participacao", "grau"),
    "expected_cents": ("valor previsto", "honorario", "honorarios", "valor"),
    "guide": ("guia", "senha", "autorizacao"),
    "notes": ("observacao", "observacoes", "obs"),
}


def guess_mapping(headers: list[str]) -> dict[str, int]:
    """Column index for each field, preferring the longest matching synonym."""
    mapping: dict[str, int] = {}
    folded = [fold(h) for h in headers]
    for field, synonyms in COLUMN_SYNONYMS.items():
        best = None
        for idx, header in enumerate(folded):
            if idx in mapping.values():
                continue
            for rank, syn in enumerate(synonyms):
                if header == syn or header.startswith(syn) or (len(syn) > 4 and syn in header):
                    score = (len(syn), -rank)
                    if best is None or score > best[0]:
                        best = (score, idx)
        if best is not None:
            mapping[field] = best[1]
    return mapping


def read_table(filename: str, content: bytes) -> list[list[str]]:
    name = filename.lower()
    if name.endswith(".xlsx"):
        from jmoraIs.reference.tuss import iter_xlsx_rows
        try:
            rows = list(iter_xlsx_rows(content))
        except Exception as exc:
            raise ImportRejected("Não foi possível ler a planilha (.xlsx).") from exc
        width = max((max(r) for r in rows if r), default=-1) + 1
        return [[r.get(i, "") for i in range(width)] for r in rows]
    if name.endswith(".csv") or name.endswith(".txt"):
        text = content.decode("utf-8-sig", errors="replace")
        sample = text[:4000]
        delimiter = max(";,\t", key=sample.count)  # Brazilian Excel exports use ';'
        return [row for row in csv.reader(io.StringIO(text), delimiter=delimiter) if any(c.strip() for c in row)]
    raise ImportRejected("Envie a planilha em .xlsx ou .csv.")


def header_row(rows: list[list[str]]) -> int:
    """First row (within 15) whose cells look like headers (most text, a date-like word)."""
    for idx, row in enumerate(rows[:15]):
        words = {fold(c) for c in row if c}
        if any(w.startswith("data") for w in words) and len(words) >= 3:
            return idx
    return 0


def surgeries_from_table(rows: list[list[str]], mapping: dict[str, int] | None = None) -> tuple[list[Surgery], list[str], dict]:
    if not rows:
        raise ImportRejected("Planilha vazia.")
    head = header_row(rows)
    headers = rows[head]
    mapping = mapping or guess_mapping(headers)
    if "date" not in mapping:
        raise ImportRejected("Não encontrei a coluna de data. Indique qual coluna é a data.")
    out, skipped = [], []
    for n, row in enumerate(rows[head + 1:], head + 2):
        cell = lambda f: (row[mapping[f]] if f in mapping and mapping[f] < len(row) else "").strip()  # noqa: E731
        iso = parse_date(cell("date"))
        if not iso:
            if any(c.strip() for c in row):
                skipped.append(f"linha {n}: data ilegível")
            continue
        try:
            out.append(Surgery(date=iso, hospital=cell("hospital"), insurer=cell("insurer"), patient=cell("patient"),
                               card=cell("card"), procedure=cell("procedure"), codes=cell("codes"), role=cell("role"),
                               expected_cents=parse_money(cell("expected_cents")), guide=cell("guide"), notes=cell("notes"),
                               source="planilha"))
        except ValueError:
            skipped.append(f"linha {n}: valores inválidos")
    return out, skipped, {"headers": headers, "mapping": mapping}


# ---------- NFS-e ----------
def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _first(root, *names: str) -> str:
    wanted = {n.lower() for n in names}
    for el in root.iter():
        if _local(el.tag).lower() in wanted and (el.text or "").strip():
            return el.text.strip()
    return ""


def invoices_from_xml(content: bytes) -> list[Invoice]:
    """ABRASF and São Paulo (NF-e Paulistana) layouts, one or many notes per file."""
    try:
        root = fromstring(content)
    except Exception as exc:
        raise ImportRejected("XML da nota inválido.") from exc
    blocks = []
    for tag in ("InfNfse", "infNFSe", "NFe", "Nfse"):  # innermost layout first, so one note is read once
        blocks = [el for el in root.iter() if _local(el.tag) == tag]
        if blocks:
            break
    blocks = blocks or [root]
    out = []
    for block in blocks:
        number = _first(block, "Numero", "NumeroNFe", "nNFSe", "NumeroNfse")
        issued = parse_date(_first(block, "DataEmissao", "DataEmissaoNFe", "dhEmi", "DataEmissaoNfse"))
        value = parse_money(_first(block, "ValorServicos", "ValorLiquidoNfse", "vServ", "ValorTotal"))
        if not (number and issued and value):
            continue
        tomador = next((el for el in block.iter() if _local(el.tag) in ("TomadorServico", "Tomador", "toma")), block)
        name = _first(tomador, "RazaoSocial", "RazaoSocialTomador", "xNome") or _first(block, "RazaoSocialTomador")
        doc = re.sub(r"\D", "", _first(tomador, "Cnpj", "CNPJ", "CPFCNPJTomador", "CPF") or "")
        out.append(Invoice(number=number.lstrip("0") or "0", issue_date=issued, hospital=name, hospital_doc=doc,
                           value_cents=value, description=_first(block, "Discriminacao", "xDescServ")[:4000], source="xml"))
    if not out:
        raise ImportRejected("Não encontrei número, data e valor da nota neste XML.")
    return out


def invoice_from_text(text: str) -> Invoice:
    """Best-effort reading of a NFS-e PDF: number, date, value and tomador; review before saving."""
    flat = " ".join(text.split())
    number = re.search(r"(?i)n[uú]mero da nota\s*:?\s*(\d+)|nfs-?e\s*n[ºo°.]*\s*:?\s*(\d+)|nota fiscal\s*n[ºo°.]*\s*:?\s*(\d+)", flat)
    issued = re.search(r"(?i)(?:data(?: e hora)? (?:de|da) emiss[aã]o)\s*:?\s*(\d{2}/\d{2}/\d{4})", flat)
    value = re.search(r"(?i)valor (?:total )?(?:dos servi[cç]os|da nota|l[ií]quido)[^0-9]{0,20}([\d.]+,\d{2})", flat)
    cnpj = re.findall(r"\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}", flat)
    tomador = re.search(r"(?i)tomador[^:]{0,40}(?:raz[aã]o social|nome)[^:]{0,15}:?\s*(.{3,80}?)(?:\s+CNPJ|\s+CPF|\s+Endere)", flat)
    if not (number and issued and value):
        raise ImportRejected("Não consegui ler número, data e valor neste PDF. Envie o XML da nota ou preencha à mão.")
    return Invoice(number=next(g for g in number.groups() if g).lstrip("0") or "0", issue_date=parse_date(issued.group(1)),
                   hospital=(tomador.group(1).strip() if tomador else ""), hospital_doc=re.sub(r"\D", "", cnpj[-1]) if len(cnpj) > 1 else "",
                   value_cents=parse_money(value.group(1)), description=flat[:4000], source="pdf")


# ---------- payments ----------
_AMOUNT = re.compile(r"R\$\s*([\d.]+,\d{2})")
_NF_REF = re.compile(r"(?i)\b(?:NF|NFS-?e|nota(?: fiscal)?)\s*(?:n[ºo°.]*)?\s*:?\s*(\d{1,10})")


def payments_from_text(text: str, payer: str, when: str, source: str) -> list[Payment]:
    """Lines that carry an amount become payment candidates; invoice numbers mentioned are kept as reference."""
    out = []
    for line in [l.strip() for l in text.splitlines() if l.strip()]:
        amounts = _AMOUNT.findall(line)
        if not amounts:
            continue
        refs = _NF_REF.findall(line)
        line_date = parse_date(line) or when
        out.append(Payment(date=line_date or date.today().isoformat(), payer=payer[:200], value_cents=parse_money(amounts[-1]),
                           reference=("NF " + ", ".join(refs)) if refs else "", description=line[:4000], source=source))
    return out


def read_email(content: bytes) -> dict:
    """Subject, sender, date, plain text and attachments (name, bytes) of a .eml file."""
    try:
        msg = BytesParser(policy=policy.default).parsebytes(content)
    except Exception as exc:
        raise ImportRejected("E-mail (.eml) inválido.") from exc
    body = msg.get_body(preferencelist=("plain", "html"))
    text = body.get_content() if body is not None else ""
    if body is not None and body.get_content_type() == "text/html":
        text = re.sub(r"<[^>]+>", " ", re.sub(r"(?i)<br\s*/?>|</p>|</tr>", "\n", text))
    attachments = [(part.get_filename() or "anexo", part.get_payload(decode=True) or b"") for part in msg.iter_attachments()]
    return {"subject": str(msg.get("subject", "")), "sender": str(msg.get("from", "")),
            "date": parse_date(str(msg.get("date", ""))) or _rfc_date(str(msg.get("date", ""))), "text": text,
            "attachments": attachments[:10]}


def _rfc_date(value: str) -> str:
    from email.utils import parsedate_to_datetime
    try:
        return parsedate_to_datetime(value).date().isoformat()
    except (TypeError, ValueError):
        return ""


PAYMENT_SYNONYMS = {
    "date": ("data do pagamento", "data pagamento", "data credito", "data"),
    "value": ("valor pago", "valor liquido", "valor repassado", "valor credito", "valor"),
    "invoice": ("nota fiscal", "nf", "nfs-e", "nfse", "nota"),
    "description": ("descricao", "historico", "paciente", "procedimento"),
}


def payments_from_table(rows: list[list[str]], payer: str, source: str) -> list[Payment]:
    head = header_row(rows)
    headers = [fold(h) for h in rows[head]] if rows else []
    cols: dict[str, int] = {}
    for field, synonyms in PAYMENT_SYNONYMS.items():
        for syn in synonyms:
            idx = next((i for i, h in enumerate(headers) if (h == syn or h.startswith(syn)) and i not in cols.values()), None)
            if idx is not None:
                cols[field] = idx
                break
    if "value" not in cols:
        raise ImportRejected("Não encontrei a coluna de valor no demonstrativo.")
    out = []
    for row in rows[head + 1:]:
        cell = lambda f: (row[cols[f]] if f in cols and cols[f] < len(row) else "").strip()  # noqa: E731
        cents = parse_money(cell("value"))
        if not cents:
            continue
        ref = re.sub(r"\D", "", cell("invoice"))
        out.append(Payment(date=parse_date(cell("date")) or date.today().isoformat(), payer=payer[:200], value_cents=cents,
                           reference=f"NF {ref.lstrip('0')}" if ref else "", description=" | ".join(c for c in row if c)[:4000],
                           source=source))
    return out
