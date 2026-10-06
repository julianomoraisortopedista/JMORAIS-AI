"""The physician's own report model, kept de-identified, used only as a format example.

The uploaded model is a real report of some patient, so it is de-identified twice: the
identifiers found on its labelled lines (``detect_identifiers``) are removed everywhere
together with the generic patterns, and the physician must review the result and confirm
that no patient data remains before it is saved. Only confirmed text is passed to the
report writer, which may copy structure and tone but never clinical content from it.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import threading
from typing import Optional

from jmoraIs.application.deidentification import DeidentifiedText, PatientIdentifiers, deidentify, detect_identifiers

MAX_STYLE_CHARS = 6000


class ReportStyleRejected(ValueError):
    pass


def deidentify_model(text: str) -> DeidentifiedText:
    found = detect_identifiers(text)
    ids = PatientIdentifiers(**{k: v for k, v in found.items() if k in PatientIdentifiers.__dataclass_fields__})
    cleaned = deidentify(text, ids)
    if len(cleaned.text.strip()) < 40:
        raise ReportStyleRejected("O modelo tem pouco texto. Envie um relatório completo em PDF com texto ou .txt.")
    return DeidentifiedText(cleaned.text.strip()[:MAX_STYLE_CHARS], cleaned.removed)


class ReportStyleStore:
    """One confirmed model per installation, as a 0600 JSON file with atomic writes."""

    def __init__(self, path: Path):
        self._path = Path(path)
        self._lock = threading.Lock()

    def load(self) -> Optional[str]:
        if not self._path.exists():
            return None
        return json.loads(self._path.read_text(encoding="utf-8")).get("text") or None

    def save(self, text: str) -> str:
        cleaned = deidentify(text).text.strip()[:MAX_STYLE_CHARS]  # generic patterns again on the edited text
        if len(cleaned) < 40:
            raise ReportStyleRejected("O modelo tem pouco texto.")
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self._path.parent, prefix=".style-")
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump({"version": 1, "text": cleaned}, handle, ensure_ascii=False)
            os.chmod(tmp, 0o600)
            os.replace(tmp, self._path)
        return cleaned

    def delete(self) -> None:
        with self._lock:
            self._path.unlink(missing_ok=True)
