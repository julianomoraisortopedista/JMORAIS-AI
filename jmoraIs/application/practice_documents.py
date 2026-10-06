"""The physician's practice data: profile and consent-form model (no patient data).

The profile (name, CRM, UF, RQE, city, contacts, address) fills headers and signatures.
The consent model is the physician's own TCLE text with "(inserir ...)" placeholders;
it is checked for identifiers before saving and filled with patient data only in the
browser. Stored as one 0600 JSON file with atomic writes.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import threading
from typing import Optional

from pydantic import BaseModel, Field

from jmoraIs.application.deidentification import detect_identifiers

MAX_CONSENT_CHARS = 20000


class PracticeRejected(ValueError):
    pass


class Profile(BaseModel):
    name: str = Field("", max_length=160)
    crm: str = Field("", max_length=20)
    uf: str = Field("", max_length=2)
    rqe: str = Field("", max_length=40)
    specialty: str = Field("Ortopedia e Traumatologia", max_length=120)
    city: str = Field("", max_length=120)
    phone: str = Field("", max_length=40)
    email: str = Field("", max_length=120)
    address: str = Field("", max_length=300)


class PracticeStore:
    def __init__(self, path: Path):
        self._path = Path(path)
        self._lock = threading.Lock()

    def _load(self) -> dict:
        return json.loads(self._path.read_text(encoding="utf-8")) if self._path.exists() else {}

    def _write(self, data: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self._path.parent, prefix=".practice-")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False)
        os.chmod(tmp, 0o600)
        os.replace(tmp, self._path)

    def profile(self) -> Profile:
        return Profile.model_validate(self._load().get("profile") or {})

    def save_profile(self, profile: Profile) -> Profile:
        with self._lock:
            data = self._load()
            data["profile"] = profile.model_dump()
            self._write(data)
        return profile

    def consent_model(self) -> Optional[str]:
        return self._load().get("consent_model")

    def save_consent_model(self, text: str) -> str:
        text = "\n".join(line.rstrip() for line in (text or "").splitlines()).strip()[:MAX_CONSENT_CHARS]
        if len(text) < 200:
            raise PracticeRejected("O termo tem pouco texto. Envie o modelo completo (.docx, PDF com texto ou .txt).")
        found = detect_identifiers(text)
        if found:
            raise PracticeRejected("O modelo parece conter dados de um paciente (" + ", ".join(sorted(found)) +
                                   "). Envie o modelo em branco, com os campos para preencher.")
        with self._lock:
            data = self._load()
            data["consent_model"] = text
            self._write(data)
        return text

    def delete_consent_model(self) -> None:
        with self._lock:
            data = self._load()
            data.pop("consent_model", None)
            self._write(data)
