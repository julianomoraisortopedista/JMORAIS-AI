"""The physician's library of past contestations (denials, glosas, medical boards).

Each entry is a real contestation the physician wrote, kept only after de-identification
and the physician's confirmation that no patient data remains. Entries carry the kind,
the procedure and the outcome, so new drafts can learn from the ones that were granted.
Stored on this computer (0600 JSON, atomic writes); never part of the repository.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import tempfile
import threading
from uuid import uuid4

from pydantic import BaseModel, Field

from jmoraIs.application.deidentification import deidentify, detect_identifiers

KINDS = ("NEGATIVA", "GLOSA", "JUNTA_MEDICA")
OUTCOMES = ("DEFERIDA", "PARCIAL", "INDEFERIDA", "PENDENTE")
MAX_APPEAL_CHARS = 14000
MAX_ENTRIES = 300


class AppealLibraryRejected(ValueError):
    pass


class AppealEntry(BaseModel):
    appeal_id: str = ""
    kind: str = Field(pattern="^(NEGATIVA|GLOSA|JUNTA_MEDICA)$")
    procedure: str = Field("", max_length=160)
    outcome: str = Field("PENDENTE", pattern="^(DEFERIDA|PARCIAL|INDEFERIDA|PENDENTE)$")
    text: str = Field(min_length=100, max_length=MAX_APPEAL_CHARS + 2000)
    created_at: str = ""
    insurer_id: str = Field("", max_length=40)           # authorization playbook insurer, when recognised
    reasons: list[str] = Field(default_factory=list, max_length=10)
    case_id: str = Field("", max_length=20)              # linked playbook case, kept in step with the outcome


def _fold(value: str) -> set[str]:
    import unicodedata
    plain = "".join(c for c in unicodedata.normalize("NFKD", value or "") if not unicodedata.combining(c)).lower()
    return {w for w in re.split(r"[^a-z0-9]+", plain) if len(w) >= 4}


class AppealLibrary:
    def __init__(self, path: Path):
        self._path = Path(path)
        self._lock = threading.Lock()

    def entries(self) -> list[AppealEntry]:
        if not self._path.exists():
            return []
        return [AppealEntry.model_validate(e) for e in json.loads(self._path.read_text(encoding="utf-8")).get("entries", [])]

    def _write(self, entries: list[AppealEntry]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self._path.parent, prefix=".appeals-")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"version": 1, "entries": [e.model_dump() for e in entries]}, handle, ensure_ascii=False)
        os.chmod(tmp, 0o600)
        os.replace(tmp, self._path)

    def add(self, entry: AppealEntry) -> AppealEntry:
        text = deidentify(entry.text).text.strip()[:MAX_APPEAL_CHARS]  # generic patterns again on the reviewed text
        found = detect_identifiers(text)
        if found:
            raise AppealLibraryRejected("Ainda há dados de paciente no texto (" + ", ".join(sorted(found)) + "). Apague e salve de novo.")
        saved = entry.model_copy(update={"appeal_id": "apl-" + uuid4().hex[:12], "text": text,
                                         "procedure": " ".join(entry.procedure.split()),
                                         "created_at": datetime.now(timezone.utc).date().isoformat()})
        with self._lock:
            entries = self.entries()
            if len(entries) >= MAX_ENTRIES:
                raise AppealLibraryRejected(f"A biblioteca já tem {MAX_ENTRIES} contestações. Exclua as antigas.")
            self._write(entries + [saved])
        return saved

    def link_case(self, appeal_id: str, case_id: str) -> None:
        with self._lock:
            entries = self.entries()
            self._write([e.model_copy(update={"case_id": case_id}) if e.appeal_id == appeal_id else e for e in entries])

    def set_outcome(self, appeal_id: str, outcome: str) -> AppealEntry:
        if outcome not in OUTCOMES:
            raise AppealLibraryRejected("Resultado inválido.")
        with self._lock:
            entries = self.entries()
            match = next((e for e in entries if e.appeal_id == appeal_id), None)
            if match is None:
                raise AppealLibraryRejected("Contestação não encontrada.")
            updated = match.model_copy(update={"outcome": outcome})
            self._write([updated if e.appeal_id == appeal_id else e for e in entries])
        return updated

    def delete(self, appeal_id: str) -> None:
        with self._lock:
            self._write([e for e in self.entries() if e.appeal_id != appeal_id])

    def examples(self, kind: str, procedure: str, limit: int = 2, insurer_id: str = "",
                 reasons: tuple = ()) -> list[AppealEntry]:
        """Most useful references: granted first, same insurer and reasons, same kind, closest procedure;
        never INDEFERIDA."""
        words = _fold(procedure)
        weight = {"DEFERIDA": 3, "PARCIAL": 2, "PENDENTE": 1}
        scored = [(weight[e.outcome] * 10 + (8 if insurer_id and e.insurer_id == insurer_id else 0)
                   + 3 * len(set(reasons) & set(e.reasons)) + (5 if e.kind == kind else 0) + len(words & _fold(e.procedure)), e)
                  for e in self.entries() if e.outcome in weight]
        scored.sort(key=lambda x: (-x[0], x[1].created_at), reverse=False)
        return [e for _, e in scored[:limit]]
