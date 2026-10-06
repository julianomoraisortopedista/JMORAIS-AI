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
MAX_LOGO_BYTES = 400_000
LOGO_TYPES = {b"\x89PNG\r\n\x1a\n": "image/png", b"\xff\xd8\xff": "image/jpeg"}


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


class Letterhead(BaseModel):
    """Printed header/footer of the practice; the logo is a PNG/JPEG stored as base64."""
    logo_base64: str = Field("", max_length=600_000)
    logo_type: str = Field("", max_length=20)
    header_lines: list[str] = Field(default_factory=list, max_length=6)
    footer: str = Field("", max_length=300)
    color: str = Field("#0f3d5e", pattern=r"^#[0-9a-fA-F]{6}$")


def validate_logo(data: bytes) -> str:
    if len(data) > MAX_LOGO_BYTES:
        raise PracticeRejected("Logo acima de 400 KB. Reduza a imagem (PNG ou JPG).")
    for magic, kind in LOGO_TYPES.items():
        if data.startswith(magic):
            return kind
    raise PracticeRejected("O logo deve ser uma imagem PNG ou JPG.")


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

    def letterhead(self) -> Letterhead:
        return Letterhead.model_validate(self._load().get("letterhead") or {})

    def save_letterhead(self, letterhead: Letterhead) -> Letterhead:
        import base64
        if letterhead.logo_base64:
            try:
                raw = base64.b64decode(letterhead.logo_base64, validate=True)
            except ValueError:
                raise PracticeRejected("Logo inválido.") from None
            letterhead = letterhead.model_copy(update={"logo_type": validate_logo(raw)})
        else:
            letterhead = letterhead.model_copy(update={"logo_type": ""})
        lines = [" ".join(line.split())[:160] for line in letterhead.header_lines if line.strip()]
        letterhead = letterhead.model_copy(update={"header_lines": lines, "footer": " ".join(letterhead.footer.split())})
        with self._lock:
            data = self._load()
            data["letterhead"] = letterhead.model_dump()
            self._write(data)
        return letterhead

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
