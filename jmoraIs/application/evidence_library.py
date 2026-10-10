"""The physician's scientific library per surgery template.

Each template keeps one clinical claim and the physician's own decisions on articles
(the portable `decision_record`: PMID, verbatim quote, abstract hash, direction, reviewer).
Records are copied only from decisions the physician made on the server in this session,
never from the browser, and every request re-verifies them in `build_justification`
(abstract unchanged, quote literal, PubMed/Crossref metadata VERIFIED) before any
reference reaches a document. No patient data: claims are generic and checked.
Stored on this computer (0600 JSON, atomic writes); never part of the repository.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import threading

from jmoraIs.application.deidentification import detect_identifiers

MAX_RECORDS = 30
MAX_TEMPLATES = 300
REQUIRED = ("pmid", "claim", "abstract_sha256", "quote", "physician_decision", "final_direction", "reviewer", "decided_at")


class EvidenceLibraryRejected(ValueError):
    pass


def _claim(value: str) -> str:
    return " ".join((value or "").split())


class EvidenceLibrary:
    def __init__(self, path: Path):
        self._path = Path(path)
        self._lock = threading.Lock()

    def _all(self) -> dict:
        if not self._path.exists():
            return {}
        return dict(json.loads(self._path.read_text(encoding="utf-8")).get("templates", {}))

    def _write(self, data: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self._path.parent, prefix=".library-")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"version": 1, "templates": data}, handle, ensure_ascii=False)
        os.chmod(tmp, 0o600)
        os.replace(tmp, self._path)

    def get(self, template_id: str) -> dict | None:
        return self._all().get(template_id)

    def save(self, template_id: str, claim: str, records: list[dict]) -> dict:
        """Replace the template's library with the physician's accepted decisions for `claim`."""
        claim = _claim(claim)
        if len(claim) < 10:
            raise EvidenceLibraryRejected("Defina a afirmação clínica antes de salvar.")
        if detect_identifiers(claim):
            raise EvidenceLibraryRejected("A afirmação não pode conter dados de paciente.")
        kept, seen = [], set()
        for record in records:
            if any(not record.get(k) for k in REQUIRED) or _claim(record["claim"]) != claim:
                continue
            if record["physician_decision"] == "REJECT" or str(record["pmid"]) in seen:
                continue
            seen.add(str(record["pmid"]))
            kept.append({k: record.get(k) for k in (*REQUIRED, "source", "ai_status", "ai_direction", "ai_rationale",
                                                     "model", "prompt_version", "note")})
        if not kept:
            raise EvidenceLibraryRejected("Nenhum artigo aceito por você para esta afirmação.")
        if len(kept) > MAX_RECORDS:
            raise EvidenceLibraryRejected(f"Mantenha até {MAX_RECORDS} artigos por cirurgia.")
        entry = {"claim": claim, "records": kept, "updated_at": datetime.now(timezone.utc).isoformat()}
        with self._lock:
            data = self._all()
            if template_id not in data and len(data) >= MAX_TEMPLATES:
                raise EvidenceLibraryRejected("Biblioteca cheia.")
            data[template_id] = entry
            self._write(data)
        return entry

    def remove(self, template_id: str, pmid: str | None = None) -> None:
        with self._lock:
            data = self._all()
            entry = data.get(template_id)
            if entry is None:
                return
            if pmid is None:
                data.pop(template_id)
            else:
                entry["records"] = [r for r in entry["records"] if str(r["pmid"]) != pmid]
                if not entry["records"]:
                    data.pop(template_id)
            self._write(data)
