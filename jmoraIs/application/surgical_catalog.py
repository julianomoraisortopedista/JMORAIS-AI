"""Surgical procedure templates: TUSS procedures, OPME kit, three suppliers, hospital packages.

Catalog data (no patient data). Every TUSS procedure code and every supplier material is
validated against the official ANS TUSS index (tables 22 and 19) when saved; the stored
material copies the official term, manufacturer and Anvisa registration. Suppliers are
alternatives chosen by the physician (CFM Res. 1.956/2010 art. 5: at least three brands
from different manufacturers, when available); no technical equivalence is inferred.
Stored as a JSON file owned by the installation.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import tempfile
import threading
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


class CatalogRejected(ValueError):
    pass


class OpmeItem(BaseModel):
    description: str = Field(min_length=2, max_length=160)       # e.g. "Componente femoral"
    quantity: int = Field(1, ge=1, le=50)


class SupplierMaterial(BaseModel):
    item_index: int = Field(ge=0, le=49)                           # which OpmeItem this fills
    tuss_code: str = Field(pattern=r"^\d{8}$")
    term: str = ""                                                 # copied from TUSS 19 on save
    manufacturer: str = ""
    anvisa: str = ""


class Supplier(BaseModel):
    label: str = Field(min_length=2, max_length=120)               # e.g. "Zimmer Biomet"
    materials: list[SupplierMaterial] = Field(default_factory=list, max_length=50)


class HospitalPackage(BaseModel):
    network: str = Field(min_length=2, max_length=120)
    package_code: str = Field("", max_length=60)
    description: str = Field("", max_length=300)
    includes_opme: Optional[bool] = None
    notes: str = Field("", max_length=500)


class ProcedureTemplate(BaseModel):
    template_id: str = Field("", max_length=40)
    name: str = Field(min_length=3, max_length=160)
    region: str = Field("", max_length=60)
    tuss_codes: list[str] = Field(default_factory=list, max_length=10)
    tuss_terms: dict[str, str] = Field(default_factory=dict)       # filled from TUSS 22 on save
    codes_confirmed: bool = False                                  # physician confirmed the codes
    regime: str = Field("", max_length=60)
    opme: list[OpmeItem] = Field(default_factory=list, max_length=50)
    suppliers: list[Supplier] = Field(default_factory=list, max_length=5)
    packages: list[HospitalPackage] = Field(default_factory=list, max_length=20)
    notes: str = Field("", max_length=1000)
    sbot_entry: str = Field("", max_length=10)                     # SBOT coding manual entry, e.g. 5.19
    icu_days: Optional[int] = Field(None, ge=0, le=60)
    ward_days: Optional[int] = Field(None, ge=0, le=120)
    anesthesia: str = Field("", max_length=120)
    consent_definition: str = Field("", max_length=3000)          # TCLE: what the procedure consists of
    consent_risks: list[str] = Field(default_factory=list, max_length=40)  # TCLE: complications, physician-written

    @field_validator("tuss_codes")
    @classmethod
    def _codes(cls, value):
        if any(not re.fullmatch(r"\d{8}", c) for c in value):
            raise ValueError("Código TUSS deve ter 8 dígitos")
        return list(dict.fromkeys(value))


def validate_against_tuss(template: ProcedureTemplate, index) -> ProcedureTemplate:
    terms = {}
    for code in template.tuss_codes:
        found = index.procedures(code)
        if not found:
            raise CatalogRejected(f"TUSS {code} não existe na tabela 22 oficial.")
        if not found[0].active:
            raise CatalogRejected(f"TUSS {code} está encerrado na tabela 22 oficial.")
        terms[code] = found[0].term
    suppliers = []
    for supplier in template.suppliers:
        materials = []
        for material in supplier.materials:
            if material.item_index >= len(template.opme):
                raise CatalogRejected("Material de fornecedor aponta para item de OPME inexistente.")
            found = index.materials(material.tuss_code)
            if not found:
                raise CatalogRejected(f"Material TUSS {material.tuss_code} não existe na tabela 19 oficial.")
            entry = found[0]
            if not entry.active:
                raise CatalogRejected(f"Material TUSS {material.tuss_code} está encerrado na tabela 19 oficial.")
            materials.append(material.model_copy(update={"term": entry.term, "manufacturer": entry.manufacturer,
                                                          "anvisa": entry.anvisa}))
        suppliers.append(supplier.model_copy(update={"materials": materials}))
    return template.model_copy(update={"tuss_terms": terms, "suppliers": suppliers})


def supplier_warnings(template: ProcedureTemplate) -> list[str]:
    warnings = []
    if template.opme:
        manufacturers = {m.manufacturer for s in template.suppliers for m in s.materials if m.manufacturer}
        complete = [s for s in template.suppliers if s.materials]
        if len(template.suppliers) < 3:
            warnings.append("Indique três fornecedores (CFM 1.956/2010, art. 5º), quando disponíveis.")
        elif len(complete) >= 3 and len(manufacturers) < 3:
            warnings.append("Os fornecedores devem ser de fabricantes diferentes (CFM 1.956/2010, art. 5º).")
        for supplier in template.suppliers:
            missing = [i.description for n, i in enumerate(template.opme)
                       if not any(m.item_index == n for m in supplier.materials)]
            if missing:
                warnings.append(f"{supplier.label}: sem material oficial para {', '.join(missing)}.")
    if not template.codes_confirmed:
        warnings.append("Códigos TUSS ainda não confirmados pelo médico.")
    return warnings


class CatalogStore:
    """JSON file store with atomic writes; one catalog per installation."""

    def __init__(self, path: Path):
        self._path = Path(path)
        self._lock = threading.Lock()

    def load(self) -> list[ProcedureTemplate]:
        if not self._path.exists():
            return []
        data = json.loads(self._path.read_text(encoding="utf-8"))
        return [ProcedureTemplate.model_validate(item) for item in data.get("templates", [])]

    def _write(self, templates: list[ProcedureTemplate]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self._path.parent, prefix=".catalog-")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"version": 1, "templates": [t.model_dump() for t in templates]}, handle, ensure_ascii=False, indent=2)
        os.chmod(tmp, 0o600)
        os.replace(tmp, self._path)

    def save(self, template: ProcedureTemplate) -> ProcedureTemplate:
        with self._lock:
            templates = self.load()
            if not template.template_id:
                template = template.model_copy(update={"template_id": "tpl-" + uuid4().hex[:12]})
            templates = [t for t in templates if t.template_id != template.template_id] + [template]
            templates.sort(key=lambda t: t.name.casefold())
            self._write(templates)
            return template

    def delete(self, template_id: str) -> None:
        with self._lock:
            self._write([t for t in self.load() if t.template_id != template_id])

    def seed(self, templates: list[ProcedureTemplate], index=None) -> None:
        """Write starter templates once; with an index, copy official TUSS terms into them."""
        with self._lock:
            if not self._path.exists():
                self._write([validate_against_tuss(t, index) if index else t for t in templates])


KNEE_TKA_KIT = [OpmeItem(description="Componente femoral", quantity=1), OpmeItem(description="Componente tibial", quantity=1),
                OpmeItem(description="Inserto de polietileno", quantity=1), OpmeItem(description="Pulse lavage (lavagem pulsátil)", quantity=1)]
TKA_SUPPLIERS = [Supplier(label="Johnson & Johnson"), Supplier(label="Zimmer Biomet"), Supplier(label="Amplitude")]


def starter_templates() -> list[ProcedureTemplate]:
    """Knee starters. Codes are candidates found in TUSS 22 (202609) and must be confirmed."""
    def t(name, codes, **kw):
        return ProcedureTemplate(template_id="tpl-" + re.sub(r"[^a-z0-9]+", "-", name.lower())[:30].strip("-"),
                                 name=name, region="Joelho", tuss_codes=codes, **kw)
    return [
        t("Artroplastia total do joelho com implantes", ["30726034"], regime="Internação",
          opme=KNEE_TKA_KIT, suppliers=TKA_SUPPLIERS),
        t("Correção de contratura do joelho em flexo", ["30726280"], regime="Internação",
          notes="Alternativa oficial com fixador externo: 30726301."),
        t("Sinovectomia total do joelho (videoartroscopia)", ["30733014"], regime="Internação"),
        t("Osteotomia femoral distal", ["30725151"], regime="Internação",
          notes="Alternativa oficial: 30726220 (osteotomias ao nível do joelho)."),
        t("Osteotomia tibial proximal", ["30726220"], regime="Internação",
          notes="Alternativa oficial: 30727162 (osteotomias da perna)."),
        t("Bloqueio de nervos geniculares", ["31403026"], regime="Ambulatorial",
          notes="Alternativa oficial: 31602118 (bloqueios anestésicos de nervos)."),
    ]


def template_from_sbot(entry, index) -> ProcedureTemplate:
    """Starting template from an SBOT manual entry; every code is checked in the official TUSS 22.

    The first CBHPM code found active in TUSS becomes the requested code; the others are
    listed in the notes for the physician to add only when they apply (and never two codes
    the manual marks as mutually exclusive). Nothing is confirmed automatically.
    """
    main, others, missing = [], [], []
    for code in entry.codes:
        found = index.procedures(code.digits) if index else []
        if not found or not found[0].active:
            missing.append(code.cbhpm)
        elif not main:
            main.append(code.digits)
        else:
            mark = f" [excludentes entre si: grupo {code.exclusive_group}]" if code.exclusive_group else ""
            others.append(f"{code.digits} {code.description} (porte {code.porte}){mark}")
    notes = [f"Base: SBOT, Manual de Diretrizes de Codificação, procedimento {entry.entry_id} (p. {entry.page})."]
    if others:
        notes.append("Códigos associados previstos (use só se realizados): " + "; ".join(others))
    if missing:
        notes.append("Não encontrados ativos na TUSS 22: " + ", ".join(missing))
    regime = "Internação" if (entry.ward_days or 0) > 0 or (entry.icu_days or 0) > 0 else "Ambulatorial"
    name = entry.name[:1] + entry.name[1:].lower()
    return ProcedureTemplate(
        name=name[:160], region="", tuss_codes=main, regime=regime, sbot_entry=entry.entry_id,
        opme=[OpmeItem(description=o.description[:160], quantity=min(max(o.quantity, 1), 50)) for o in entry.opme[:50]],
        icu_days=entry.icu_days, ward_days=entry.ward_days, consent_definition=entry.description[:3000],
        notes=" ".join(notes)[:1000])
