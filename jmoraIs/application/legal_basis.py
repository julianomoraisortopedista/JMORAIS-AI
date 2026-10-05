"""Legal basis section for an insurer coverage request — fixed sources, no generated law.

Every legal text below is a verbatim excerpt checked against an official source on
the date in `LEGAL_SOURCES_CHECKED_ON`; nothing is produced by a model. The section
is assembled deterministically from (a) facts the physician states about coverage
(`CoverageContext`) and (b) the re-verified scientific evidence of the justification
draft. For procedures outside the ANS list it reports each of the five cumulative
STF requirements (ADI 7265) as MET / PENDING / NOT_MET instead of asserting that
coverage is due. The output is support material that requires legal review.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from jmoraIs.application.scientific_justification import GUIDELINE_TYPES, JustificationDraft
from jmoraIs.scientific_domain import SupportDirection

LEGAL_SOURCES_CHECKED_ON = "2026-10-05"


@dataclass(frozen=True)
class LegalSource:
    source_id: str
    citation: str
    excerpt: str
    url: str


LEGAL_SOURCES: dict[str, LegalSource] = {s.source_id: s for s in (
    LegalSource(
        "lei9656-art10-p12", "Lei nº 9.656/1998, art. 10, § 12 (incluído pela Lei nº 14.454/2022)",
        "O rol de procedimentos e eventos em saúde suplementar, atualizado pela ANS a cada nova incorporação, "
        "constitui a referência básica para os planos privados de assistência à saúde contratados a partir de "
        "1º de janeiro de 1999 e para os contratos adaptados a esta Lei e fixa as diretrizes de atenção à saúde.",
        "https://www.planalto.gov.br/ccivil_03/leis/l9656.htm"),
    LegalSource(
        "lei9656-art10-p13", "Lei nº 9.656/1998, art. 10, § 13 (incluído pela Lei nº 14.454/2022)",
        "Em caso de tratamento ou procedimento prescrito por médico ou odontólogo assistente que não estejam "
        "previstos no rol referido no § 12 deste artigo, a cobertura deverá ser autorizada pela operadora de "
        "planos de assistência à saúde, desde que: I - exista comprovação da eficácia, à luz das ciências da "
        "saúde, baseada em evidências científicas e plano terapêutico; ou II - existam recomendações pela "
        "Comissão Nacional de Incorporação de Tecnologias no Sistema Único de Saúde (Conitec), ou exista "
        "recomendação de, no mínimo, 1 (um) órgão de avaliação de tecnologias em saúde que tenha renome "
        "internacional, desde que sejam aprovadas também para seus nacionais.",
        "https://www.planalto.gov.br/ccivil_03/leis/l9656.htm"),
    LegalSource(
        "lei9656-art35c", "Lei nº 9.656/1998, art. 35-C, I e II (redação da Lei nº 11.935/2009)",
        "É obrigatória a cobertura do atendimento nos casos: I - de emergência, como tal definidos os que "
        "implicarem risco imediato de vida ou de lesões irreparáveis para o paciente, caracterizado em "
        "declaração do médico assistente; II - de urgência, assim entendidos os resultantes de acidentes "
        "pessoais ou de complicações no processo gestacional;",
        "https://www.planalto.gov.br/ccivil_03/leis/l9656.htm"),
    LegalSource(
        "stf-adi7265", "STF, ADI 7.265 (julgamento concluído em setembro de 2025), tese",
        "É constitucional a imposição legal de cobertura de tratamentos ou procedimentos fora do rol da ANS, "
        "desde que preenchidos os parâmetros técnicos e jurídicos fixados nesta decisão.",
        "https://www.cnj.jus.br/wp-content/uploads/2026/07/cartilha-adi-7-265.pdf"),
    LegalSource(
        "stj-sumula608", "STJ, Súmula 608",
        "Aplica-se o Código de Defesa do Consumidor aos contratos de plano de saúde, salvo os administrados "
        "por entidades de autogestão.",
        "https://www.stj.jus.br/sites/portalp/Paginas/Comunicacao/Noticias-antigas/2018/"
        "2018-04-16_15-47_STJ-edita-quatro-novas-sumulas-e-cancela-uma-sobre-planos-de-saude.aspx"),
    LegalSource(
        "cdc-art47", "Lei nº 8.078/1990 (CDC), art. 47",
        "As cláusulas contratuais serão interpretadas de maneira mais favorável ao consumidor.",
        "https://www.planalto.gov.br/ccivil_03/leis/l8078compilado.htm"),
)}

# The five cumulative requirements as summarized in the CNJ guide on ADI 7.265.
STF_REQUIREMENTS = (
    ("prescricao", "Prescrição por médico ou odontólogo assistente habilitado"),
    ("ans", "Inexistência de negativa da ANS ou de pendência de análise de atualização do rol"),
    ("alternativa", "Ausência de alternativa terapêutica no rol da ANS"),
    ("evidencia", "Comprovação de eficácia e segurança à luz da medicina baseada em evidências de alto grau "
                  "ou ATS, respaldadas por evidências científicas de alto nível"),
    ("anvisa", "Existência de registro na Anvisa"),
)


class RolStatus(str, Enum):
    IN_ROL = "SIM"
    NOT_IN_ROL = "NAO"
    UNKNOWN = "NAO_INFORMADO"


class AnsAnalysis(str, Enum):
    NEVER_ANALYZED = "SEM_ANALISE"
    REJECTED = "NEGADA"
    PENDING = "PENDENTE"
    UNKNOWN = "NAO_INFORMADO"


class Urgency(str, Enum):
    ELECTIVE = "ELETIVA"
    URGENCY = "URGENCIA"
    EMERGENCY = "EMERGENCIA"


class RequirementStatus(str, Enum):
    MET = "ATENDIDO"
    PENDING = "PENDENTE"
    NOT_MET = "NAO_ATENDIDO"


@dataclass(frozen=True)
class CoverageContext:
    """Facts stated by the physician. No patient identifiers."""
    procedure: str
    rol_status: RolStatus = RolStatus.UNKNOWN
    urgency: Urgency = Urgency.ELECTIVE
    ans_analysis: AnsAnalysis = AnsAnalysis.UNKNOWN
    no_rol_alternative_reason: str = ""
    anvisa_registration: str = ""
    prescriber_registration: str = ""
    prior_request_to_operator: Optional[bool] = None
    self_managed_plan: Optional[bool] = None


@dataclass(frozen=True)
class RequirementCheck:
    key: str
    label: str
    status: RequirementStatus
    basis: str


@dataclass(frozen=True)
class LegalSection:
    paragraphs: tuple[str, ...]
    requirements: tuple[RequirementCheck, ...]
    sources: tuple[LegalSource, ...]
    warnings: tuple[str, ...] = field(default_factory=tuple)
    closing: tuple[str, ...] = field(default_factory=tuple)  # shown after the requirement checklist


def _quote(source_id: str) -> str:
    source = LEGAL_SOURCES[source_id]
    return f'{source.citation}: "{source.excerpt}"'


def _evidence_check(draft: JustificationDraft) -> RequirementCheck:
    supporting = draft.by_direction(SupportDirection.SUPPORTING)
    high = [r for r in supporting if r.high_level]
    guidelines = [r for r in supporting if any(t in GUIDELINE_TYPES for t in r.study_types)]
    if high:
        refs = ", ".join(f"[{r.number}]" for r in high)
        return RequirementCheck("evidencia", STF_REQUIREMENTS[3][1], RequirementStatus.MET,
                                f"{len(high)} evidência(s) favorável(is) de alto nível confirmada(s) pelo médico, "
                                f"classificadas no PubMed como ensaio randomizado, revisão sistemática ou "
                                f"meta-análise: {refs}.")
    detail = f" Há {len(guidelines)} diretriz(es) favorável(is)." if guidelines else ""
    return RequirementCheck("evidencia", STF_REQUIREMENTS[3][1], RequirementStatus.NOT_MET if supporting else RequirementStatus.PENDING,
                            "Nenhuma evidência favorável de alto nível (ensaio randomizado, revisão sistemática "
                            "ou meta-análise) entre as referências confirmadas." + detail)


def _requirements(context: CoverageContext, draft: JustificationDraft) -> tuple[RequirementCheck, ...]:
    label = dict(STF_REQUIREMENTS)
    checks = [RequirementCheck(
        "prescricao", label["prescricao"],
        RequirementStatus.MET if context.prescriber_registration.strip() else RequirementStatus.PENDING,
        f"Prescritor: {context.prescriber_registration.strip()}." if context.prescriber_registration.strip()
        else "Informar o registro profissional (CRM/CRO) do prescritor.")]
    ans = {AnsAnalysis.NEVER_ANALYZED: (RequirementStatus.MET, "Informado que a tecnologia não foi analisada nem negada pela ANS."),
           AnsAnalysis.REJECTED: (RequirementStatus.NOT_MET, "Informado que a ANS analisou e negou a incorporação."),
           AnsAnalysis.PENDING: (RequirementStatus.NOT_MET, "Informado que há análise de atualização do rol pendente na ANS."),
           AnsAnalysis.UNKNOWN: (RequirementStatus.PENDING, "Verificar a situação da tecnologia na ANS.")}[context.ans_analysis]
    checks.append(RequirementCheck("ans", label["ans"], *ans))
    reason = context.no_rol_alternative_reason.strip()
    checks.append(RequirementCheck(
        "alternativa", label["alternativa"], RequirementStatus.MET if reason else RequirementStatus.PENDING,
        f"Justificativa do médico: {reason}" if reason else "O médico deve justificar por que as alternativas do rol "
        "não são adequadas para este caso."))
    checks.append(_evidence_check(draft))
    anvisa = context.anvisa_registration.strip()
    checks.append(RequirementCheck(
        "anvisa", label["anvisa"], RequirementStatus.MET if anvisa else RequirementStatus.PENDING,
        f"Registro informado: {anvisa} (conferir na consulta pública da Anvisa)." if anvisa
        else "Informar o registro na Anvisa do material/tecnologia, quando aplicável."))
    return tuple(checks)


def build_legal_section(context: CoverageContext, draft: JustificationDraft) -> LegalSection:
    if not context.procedure.strip():
        raise ValueError("procedure description is required")
    used, paragraphs, warnings, requirements, closing = [], [], [], (), []
    procedure = context.procedure.strip()
    if context.rol_status is RolStatus.IN_ROL:
        used.append("lei9656-art10-p12")
        paragraphs.append(f"Segundo o médico assistente, o procedimento \"{procedure}\" consta do Rol de Procedimentos e "
                          f"Eventos em Saúde da ANS. {_quote('lei9656-art10-p12')}")
    elif context.rol_status is RolStatus.NOT_IN_ROL:
        used += ["lei9656-art10-p12", "lei9656-art10-p13", "stf-adi7265"]
        paragraphs.append(f"Segundo o médico assistente, o procedimento \"{procedure}\" não consta do Rol da ANS. "
                          f"{_quote('lei9656-art10-p12')} {_quote('lei9656-art10-p13')}")
        paragraphs.append(f"{_quote('stf-adi7265')} Conforme a decisão, a cobertura fora do rol exige o preenchimento "
                          "cumulativo dos requisitos abaixo; a situação de cada um neste pedido está indicada a seguir.")
        requirements = _requirements(context, draft)
        if any(r.status is not RequirementStatus.MET for r in requirements):
            warnings.append("Nem todos os requisitos cumulativos do STF estão atendidos ou comprovados; complete os "
                            "itens pendentes antes do envio.")
    else:
        warnings.append("Informe se o procedimento consta do Rol da ANS; a fundamentação legal depende disso.")
    if context.urgency is not Urgency.ELECTIVE:
        used.append("lei9656-art35c")
        kind = "emergência" if context.urgency is Urgency.EMERGENCY else "urgência"
        paragraphs.append(f"O médico assistente caracteriza o caso como de {kind}. {_quote('lei9656-art35c')}")
    if context.self_managed_plan is True:
        closing.append("Plano informado como de autogestão: segundo a Súmula 608 do STJ, o CDC não se aplica a esse "
                          f"contrato. {_quote('stj-sumula608')}")
        used.append("stj-sumula608")
    else:
        used += ["stj-sumula608", "cdc-art47"]
        caveat = "" if context.self_managed_plan is False else " (confirmar que o plano não é de autogestão)"
        closing.append(f"Relação de consumo{caveat}: {_quote('stj-sumula608')} {_quote('cdc-art47')}")
    opposing = len(draft.by_direction(SupportDirection.OPPOSING))
    if opposing:
        closing.append(f"Em respeito à transparência, a fundamentação científica inclui {opposing} evidência(s) "
                          "contrária(s), apresentadas junto às favoráveis.")
    if context.prior_request_to_operator is not True:
        warnings.append("Registre o pedido prévio à operadora (com protocolo) e a resposta recebida; o STF exige essa "
                        "prova em eventual discussão judicial.")
    return LegalSection(tuple(paragraphs), requirements, tuple(LEGAL_SOURCES[s] for s in dict.fromkeys(used)),
                        tuple(warnings), tuple(closing))


STATUS_PT = {RequirementStatus.MET: "atendido", RequirementStatus.PENDING: "pendente",
             RequirementStatus.NOT_MET: "não atendido"}


def render_legal_markdown(section: LegalSection) -> str:
    lines = ["## Fundamentação jurídica", ""]
    lines += [p + "\n" for p in section.paragraphs]
    if section.requirements:
        lines += ["### Requisitos cumulativos (STF, ADI 7.265)", ""]
        lines += [f"{i}. **{r.label}** — {STATUS_PT[r.status]}. {r.basis}" for i, r in enumerate(section.requirements, 1)]
        lines.append("")
    lines += [p + "\n" for p in section.closing]
    if section.warnings:
        lines += ["### Pendências", ""] + [f"- {w}" for w in section.warnings] + [""]
    lines += ["### Fontes legais", ""]
    lines += [f"- {s.citation}. Disponível em: {s.url}" for s in section.sources]
    lines += ["", f"Textos legais conferidos nas fontes oficiais em {LEGAL_SOURCES_CHECKED_ON}. Texto de apoio montado "
              "a partir de modelos fixos, sem redação por IA; requer revisão por advogado.", ""]
    return "\n".join(lines)
