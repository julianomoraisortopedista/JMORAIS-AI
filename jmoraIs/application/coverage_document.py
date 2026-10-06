"""Printable coverage-request document (HTML, A4) for the insurer — draft for signature.

Combines the physician's own clinical text, the re-verified scientific justification
and the fixed-source legal section. Patient identification is left as blank lines to be
filled on the printed/PDF copy, so the system never stores direct identifiers. Every
dynamic value is HTML-escaped; no script is emitted. Print to PDF from the browser.
"""
from __future__ import annotations

from dataclasses import dataclass
from html import escape
import re

from jmoraIs.application.legal_basis import STATUS_PT, LegalSection, LEGAL_SOURCES_CHECKED_ON, CoverageContext
from jmoraIs.application.scientific_justification import SECTION_TITLES, JustificationDraft

CSS = """
@page { size: A4; margin: 18mm 16mm; }
body { font-family: Georgia, 'Times New Roman', serif; font-size: 11pt; line-height: 1.45; color: #111; max-width: 180mm; margin: 0 auto; }
h1 { font-size: 15pt; margin: 0 0 4pt; } h2 { font-size: 12.5pt; margin: 16pt 0 6pt; border-bottom: 1px solid #999; }
h3 { font-size: 11pt; margin: 10pt 0 4pt; } .muted { color: #555; font-size: 9.5pt; }
.draft { border: 1.5px solid #b00; color: #b00; padding: 4pt 8pt; font-weight: bold; text-align: center; margin: 8pt 0; }
.fill { border-bottom: 1px solid #333; display: inline-block; min-width: 70mm; height: 12pt; }
table.ident td { padding: 3pt 6pt 3pt 0; vertical-align: bottom; } blockquote { margin: 4pt 0 4pt 12pt; font-style: italic; }
ol.refs li { margin-bottom: 4pt; } .req-ATENDIDO { color: #0a5a0a; } .req-PENDENTE { color: #8a5a00; } .req-NAO_ATENDIDO { color: #b00; }
.sign { margin-top: 36pt; } .sign .line { border-top: 1px solid #333; width: 85mm; margin-top: 40pt; padding-top: 3pt; }
@media print { .noprint { display: none; } }
"""


def _p(text: str) -> str:
    return "".join(f"<p>{escape(part)}</p>" for part in text.strip().split("\n\n") if part.strip())


@dataclass(frozen=True)
class RequestDetails:
    """Codes and materials stated by the physician (never generated)."""
    icd10: tuple[str, ...] = ()
    tuss: tuple[tuple[str, str], ...] = ()            # (code, description)
    opme: tuple[tuple[str, str, int], ...] = ()       # (description, anvisa registration, quantity)
    laterality: str = ""
    regime: str = ""
    # Alternatives per CFM 1.956/2010 art. 5: (supplier label, ((item, qty, official term, manufacturer, anvisa, tuss), ...))
    brands: tuple = ()

    def __post_init__(self):
        if any(not re.fullmatch(r"[A-Z]\d{2}(\.\d{1,2})?", c) for c in self.icd10):
            raise ValueError("CID-10 inválido")
        if any(not re.fullmatch(r"\d{8}", code) for code, _ in self.tuss):
            raise ValueError("Código TUSS deve ter 8 dígitos")
        if any(q < 1 or q > 50 for _, _, q in self.opme):
            raise ValueError("Quantidade de OPME inválida")


def _facts_html(facts) -> str:
    groups: dict[str, list] = {}
    for fact in facts:
        groups.setdefault(fact["category_label"], []).append(fact)
    out = []
    for label, items in groups.items():
        out.append(f"<h3>{escape(label)}</h3><ul>")
        for f in items:
            out.append(f"<li>{escape(f['statement'])} <span class=\"muted\">({escape(f['source'])}: “{escape(f['quote'])}”)</span></li>")
        out.append("</ul>")
    return "".join(out)


def render_coverage_html(draft: JustificationDraft, legal: LegalSection, context: CoverageContext,
                         clinical_summary: str = "", request: "RequestDetails | None" = None,
                         clinical_facts: tuple = ()) -> str:
    out = ["<!doctype html><html lang=\"pt-BR\"><head><meta charset=\"utf-8\">",
           "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">",
           f"<title>Solicitação de cobertura — {escape(context.procedure)}</title><style>{CSS}</style></head><body>",
           "<h1>Solicitação de autorização de procedimento — justificativa técnica</h1>",
           "<div class=\"draft\">RASCUNHO — exige revisão e assinatura do médico responsável antes do envio</div>",
           "<p class=\"noprint muted\">Use Imprimir &gt; Salvar como PDF no navegador.</p>",
           "<h2>Identificação</h2><table class=\"ident\">"]
    for key, label in (("paciente", "Paciente"), ("carteirinha", "Carteirinha / nº do beneficiário"),
                       ("operadora", "Operadora / plano"), ("data", "Data")):
        out.append(f"<tr><td>{label}:</td><td><span class=\"fill\" data-ident=\"{key}\"></span></td></tr>")
    out.append(f"<tr><td>Médico assistente:</td><td>{escape(context.prescriber_registration) or '<span class=\"fill\"></span>'}</td></tr></table>")
    out.append(f"<h2>Procedimento solicitado</h2><p><strong>{escape(context.procedure)}</strong></p>")
    if context.anvisa_registration.strip():
        out.append(f"<p>Registro Anvisa informado: {escape(context.anvisa_registration)}</p>")
    if request is not None:
        out.append("<table class=\"ident\">")
        if request.tuss:
            out.append("<tr><td>TUSS:</td><td>" + "<br>".join(f"{escape(c)} — {escape(d)}" for c, d in request.tuss) + "</td></tr>")
        if request.icd10:
            out.append(f"<tr><td>CID-10:</td><td>{escape(', '.join(request.icd10))}</td></tr>")
        if request.laterality:
            out.append(f"<tr><td>Lateralidade:</td><td>{escape(request.laterality)}</td></tr>")
        if request.regime:
            out.append(f"<tr><td>Regime:</td><td>{escape(request.regime)}</td></tr>")
        out.append("</table>")
        if request.opme:
            out.append("<h3>OPME solicitado</h3><table class=\"ident\"><tr><td><strong>Material</strong></td>"
                       "<td><strong>Registro Anvisa</strong></td><td><strong>Qtd.</strong></td></tr>")
            out += [f"<tr><td>{escape(d)}</td><td>{escape(a)}</td><td>{q}</td></tr>" for d, a, q in request.opme]
            out.append("</table>")
        if request.brands:
            out.append("<h3>Marcas indicadas (fabricantes diferentes, registro Anvisa — CFM 1.956/2010, art. 5º)</h3>")
            for label, materials in request.brands:
                out.append(f"<p><strong>{escape(label)}</strong></p><table class=\"ident\"><tr><td><strong>Item</strong></td>"
                           "<td><strong>Material (TUSS 19)</strong></td><td><strong>Fabricante</strong></td>"
                           "<td><strong>Anvisa</strong></td><td><strong>Qtd.</strong></td></tr>")
                out += [f"<tr><td>{escape(i)}</td><td>{escape(c)} — {escape(t)}</td><td>{escape(m)}</td><td>{escape(a)}</td>"
                        f"<td>{q}</td></tr>" for i, q, t, m, a, c in materials]
                out.append("</table>")
    out.append("<h2>Justificativa clínica</h2>")
    if clinical_summary.strip():
        out.append(_p(clinical_summary))
    if clinical_facts:
        out.append("<p class=\"muted\">Fatos clínicos confirmados pelo médico, com o trecho do documento de origem.</p>")
        out.append(_facts_html(clinical_facts))
    if not clinical_summary.strip() and not clinical_facts:
        out.append("<p class=\"muted\">[A ser redigida pelo médico assistente com os dados clínicos do caso.]</p>")
    out.append("<h2>Fundamentação científica</h2>")
    out.append(f"<p><strong>Afirmação avaliada:</strong> {escape(draft.claim)}</p>")
    out.append("<p class=\"muted\">Somente artigos com metadados verificados no PubMed e no Crossref, classificados "
               "com confirmação médica; trechos literais dos resumos publicados (em inglês).</p>")
    for direction, title in SECTION_TITLES.items():
        items = draft.by_direction(direction)
        if not items:
            continue
        out.append(f"<h3>{escape(title)} ({len(items)})</h3>")
        for ref in items:
            kind = f" — {escape(ref.study_label)}" if ref.study_label else ""
            out.append(f"<p>[{ref.number}] PMID {escape(ref.pmid)}{kind}</p><blockquote>“{escape(ref.quote)}”</blockquote>")
    if not draft.references:
        out.append("<p class=\"muted\">Nenhuma evidência verificada e confirmada.</p>")
    out.append("<h2>Fundamentação jurídica</h2>")
    out += [_p(p) for p in legal.paragraphs]
    if legal.requirements:
        out.append("<h3>Requisitos cumulativos (STF, ADI 7.265)</h3><ol>")
        for r in legal.requirements:
            out.append(f"<li><strong>{escape(r.label)}</strong> — <span class=\"req-{r.status.value}\">"
                       f"{STATUS_PT[r.status]}</span>. {escape(r.basis)}</li>")
        out.append("</ol>")
    out += [_p(p) for p in legal.closing]
    if legal.warnings:
        out.append("<h3>Pendências antes do envio</h3><ul>" + "".join(f"<li>{escape(w)}</li>" for w in legal.warnings) + "</ul>")
    out.append("<h2>Referências</h2><ol class=\"refs\">")
    out += [f"<li>{escape(ref.vancouver)}</li>" for ref in draft.references]
    out.append("</ol><h3>Fontes legais</h3><ul>")
    out += [f"<li>{escape(s.citation)}. Disponível em: {escape(s.url)}</li>" for s in legal.sources]
    out.append("</ul>")
    out.append(f"<p class=\"muted\">Textos legais conferidos nas fontes oficiais em {LEGAL_SOURCES_CHECKED_ON}. "
               "Evidências e referências reverificadas no momento da geração "
               f"({escape(draft.created_at.strftime('%d/%m/%Y %H:%M UTC'))}). Documento de apoio montado sem "
               "redação por IA; requer revisão médica e, se necessário, jurídica.</p>")
    out.append("<div class=\"sign\"><div class=\"line\">Assinatura e carimbo do médico assistente (CRM)</div></div>")
    out.append("</body></html>")
    return "\n".join(out)
