"""Official ANS TUSS tables (22 procedures, 19 materials/OPME) as a local search index.

Built only from the ANS "Padrão TISS - Representação de Conceitos em Saúde" package
(https://www.ans.gov.br/arquivos/extras/tiss/). Codes, terms, manufacturers and Anvisa
registrations are copied verbatim; nothing is inferred. Expired terms are kept but
flagged. Lookups are read-only.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import io
from pathlib import Path
import re
import sqlite3
import unicodedata
import zipfile
from xml.etree.ElementTree import iterparse

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
EXCEL_EPOCH = date(1899, 12, 30)


def _fold(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", value or "") if not unicodedata.combining(c)).lower()


def _col(ref: str) -> int:
    n = 0
    for ch in ref:
        if not ch.isalpha():
            break
        n = n * 26 + ord(ch.upper()) - 64
    return n - 1


def _excel_date(value: str | None) -> str | None:
    try:
        return (EXCEL_EPOCH + timedelta(days=int(float(value)))).isoformat() if value else None
    except ValueError:
        return None


def iter_xlsx_rows(content: bytes, only: str | None = None):
    """Yield {column_index: text} for each non-empty row of every worksheet, or of the sheet file `only` (stdlib only)."""
    book = zipfile.ZipFile(io.BytesIO(content))
    shared: list[str] = []
    if "xl/sharedStrings.xml" in book.namelist():
        for _, el in iterparse(book.open("xl/sharedStrings.xml")):
            if el.tag == NS + "si":
                shared.append("".join(t.text or "" for t in el.iter(NS + "t")))
                el.clear()
    for name in sorted(n for n in book.namelist() if n.startswith("xl/worksheets/sheet") and (only is None or n == only)):
        for _, el in iterparse(book.open(name)):
            if el.tag != NS + "row":
                continue
            values = {}
            for cell in el.findall(NS + "c"):
                v, kind, text = cell.find(NS + "v"), cell.get("t"), None
                if kind == "s" and v is not None:
                    text = shared[int(v.text)]
                elif kind == "inlineStr":
                    node = cell.find(NS + "is")
                    text = "".join(i.text or "" for i in node.iter(NS + "t")) if node is not None else None
                elif v is not None:
                    text = v.text
                if text is not None and text.strip():
                    values[_col(cell.get("r"))] = text.strip()
            el.clear()
            if values:
                yield values


SCHEMA = """
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE procedures(code TEXT PRIMARY KEY, term TEXT, start TEXT, end TEXT);
CREATE TABLE materials(code TEXT PRIMARY KEY, term TEXT, model TEXT, manufacturer TEXT, anvisa TEXT,
                       risk_class TEXT, technical_name TEXT, start TEXT, end TEXT);
CREATE VIRTUAL TABLE procedures_fts USING fts5(code UNINDEXED, folded);
CREATE VIRTUAL TABLE materials_fts USING fts5(code UNINDEXED, folded);
"""


def build_index(official_zip: Path, output: Path) -> dict:
    version = re.search(r"(\d{6})", official_zip.name)
    if output.exists():
        output.unlink()
    db = sqlite3.connect(output)
    db.executescript(SCHEMA)
    counts = {"procedures": 0, "materials": 0}
    with zipfile.ZipFile(official_zip) as package:
        for name in package.namelist():
            if not name.endswith(".xlsx") or "~$" in name:
                continue
            if "TUSS 22" in name:
                for row in iter_xlsx_rows(package.read(name)):
                    code = row.get(0, "")
                    if re.fullmatch(r"\d{8}", code):
                        db.execute("INSERT OR REPLACE INTO procedures VALUES(?,?,?,?)",
                                   (code, row.get(1, ""), _excel_date(row.get(3)), _excel_date(row.get(4))))
                        db.execute("INSERT INTO procedures_fts VALUES(?,?)", (code, _fold(row.get(1, ""))))
                        counts["procedures"] += 1
            elif "TUSS 19" in name:
                for row in iter_xlsx_rows(package.read(name)):
                    code = row.get(0, "")
                    if re.fullmatch(r"\d{8}", code):
                        values = (code, row.get(1, ""), row.get(2, ""), row.get(3, ""), row.get(7, ""), row.get(8, ""),
                                  row.get(9, ""), _excel_date(row.get(4)), _excel_date(row.get(5)))
                        db.execute("INSERT OR REPLACE INTO materials VALUES(?,?,?,?,?,?,?,?,?)", values)
                        db.execute("INSERT INTO materials_fts VALUES(?,?)",
                                   (code, _fold(" ".join((values[1], values[2], values[3], values[6])))))
                        counts["materials"] += 1
    db.execute("INSERT INTO meta VALUES('version',?)", (version.group(1) if version else "unknown",))
    db.execute("INSERT INTO meta VALUES('source','ANS - Padrão TISS - Representação de Conceitos em Saúde')")
    db.commit()
    db.close()
    return counts


@dataclass(frozen=True)
class TussEntry:
    table: str
    code: str
    term: str
    active: bool
    model: str = ""
    manufacturer: str = ""
    anvisa: str = ""
    risk_class: str = ""
    technical_name: str = ""


class TussIndex:
    def __init__(self, path: Path, today=date.today):
        self._path, self._today = Path(path), today
        if not self._path.exists():
            raise FileNotFoundError("TUSS index not built")

    def _connect(self):
        return sqlite3.connect(f"file:{self._path}?mode=ro", uri=True)

    def version(self) -> str:
        with self._connect() as db:
            row = db.execute("SELECT value FROM meta WHERE key='version'").fetchone()
        return row[0] if row else "unknown"

    def _active(self, end: str | None) -> bool:
        return not end or end > self._today().isoformat()

    @staticmethod
    def _match(query: str) -> str:
        words = [w for w in re.findall(r"[a-z0-9]+", _fold(query)) if len(w) >= 2][:8]
        return " AND ".join(f'"{w}"*' for w in words)

    def procedures(self, query: str, limit: int = 20) -> list[TussEntry]:
        with self._connect() as db:
            if re.fullmatch(r"\d{8}", query.strip()):
                rows = db.execute("SELECT code, term, end FROM procedures WHERE code=?", (query.strip(),)).fetchall()
            else:
                match = self._match(query)
                if not match:
                    return []
                rows = db.execute("SELECT p.code, p.term, p.end FROM procedures_fts f JOIN procedures p ON p.code=f.code "
                                  "WHERE procedures_fts MATCH ? ORDER BY rank LIMIT ?", (match, limit)).fetchall()
        return [TussEntry("22", c, t, self._active(e)) for c, t, e in rows]

    def materials(self, query: str, manufacturer: str = "", limit: int = 30) -> list[TussEntry]:
        with self._connect() as db:
            if re.fullmatch(r"\d{8}", query.strip()):
                rows = db.execute("SELECT code,term,model,manufacturer,anvisa,risk_class,technical_name,end FROM materials "
                                  "WHERE code=?", (query.strip(),)).fetchall()
            else:
                match = self._match(query + " " + manufacturer)
                if not match:
                    return []
                rows = db.execute("SELECT m.code,m.term,m.model,m.manufacturer,m.anvisa,m.risk_class,m.technical_name,m.end "
                                  "FROM materials_fts f JOIN materials m ON m.code=f.code WHERE materials_fts MATCH ? "
                                  "ORDER BY rank LIMIT ?", (match, limit)).fetchall()
        return [TussEntry("19", c, t, self._active(e), mo, ma, an, rc, tn) for c, t, mo, ma, an, rc, tn, e in rows]
