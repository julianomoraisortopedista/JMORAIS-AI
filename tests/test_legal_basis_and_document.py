from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha256

import pytest

from jmoraIs.application.coverage_document import render_coverage_html
from jmoraIs.application.legal_basis import (
    LEGAL_SOURCES, AnsAnalysis, CoverageContext, RequirementStatus, RolStatus, Urgency,
    build_legal_section, render_legal_markdown,
)
from jmoraIs.application.scientific_justification import JustificationDraft, JustifiedReference
from jmoraIs.scientific_domain import SupportDirection

NOW = datetime(2026, 10, 5, tzinfo=timezone.utc)


def ref(number=1, direction=SupportDirection.SUPPORTING, types=("Journal Article", "Randomized Controlled Trial")):
    return JustifiedReference(number, str(26488691 + number), direction, "quoted passage", f"Ref {number}.", "pkg",
                              "CRM-SP-1", "ACCEPT", "claude-opus-5-5", types)


def draft(*refs):
    return JustificationDraft("Total knee replacement improves pain", tuple(refs), (), NOW)


def context(**changes):
    values = dict(procedure="Artroplastia total do joelho", rol_status=RolStatus.NOT_IN_ROL,
                  ans_analysis=AnsAnalysis.NEVER_ANALYZED, no_rol_alternative_reason="Alternativas esgotadas",
                  anvisa_registration="80000000000", prescriber_registration="CRM-SP 1", prior_request_to_operator=True,
                  self_managed_plan=False)
    values.update(changes)
    return CoverageContext(**values)


# Excerpts were checked verbatim against the official sources on 2026-10-05
# (Planalto, CNJ guide on ADI 7.265, STJ). Re-verify there before changing any text.
PINNED = {
    "lei9656-art10-p12": "c8aad90b", "lei9656-art10-p13": "30a60ccc", "lei9656-art35c": "4b251613",
    "stf-adi7265": "c3a9f4e4", "stj-sumula608": "69ed5d16", "cdc-art47": "24348632",
}


def test_legal_excerpts_are_pinned_to_the_verified_text():
    actual = {k: sha256(s.excerpt.encode()).hexdigest()[:8] for k, s in LEGAL_SOURCES.items()}
    assert actual == PINNED
    assert all(s.url.startswith("https://www.") for s in LEGAL_SOURCES.values())


def test_outside_rol_all_requirements_met_lists_five_checks():
    section = build_legal_section(context(), draft(ref()))
    assert [r.status for r in section.requirements] == [RequirementStatus.MET] * 5
    assert section.warnings == ()
    text = render_legal_markdown(section)
    assert "Requisitos cumulativos (STF, ADI 7.265)" in text and "requer revisão por advogado" in text
    assert [s.source_id for s in section.sources] == ["lei9656-art10-p12", "lei9656-art10-p13", "stf-adi7265",
                                                      "stj-sumula608", "cdc-art47"]


@pytest.mark.parametrize("changes,key,status", [
    (dict(ans_analysis=AnsAnalysis.REJECTED), "ans", RequirementStatus.NOT_MET),
    (dict(ans_analysis=AnsAnalysis.PENDING), "ans", RequirementStatus.NOT_MET),
    (dict(ans_analysis=AnsAnalysis.UNKNOWN), "ans", RequirementStatus.PENDING),
    (dict(no_rol_alternative_reason=" "), "alternativa", RequirementStatus.PENDING),
    (dict(anvisa_registration=""), "anvisa", RequirementStatus.PENDING),
    (dict(prescriber_registration=""), "prescricao", RequirementStatus.PENDING),
])
def test_unmet_requirements_are_reported_not_asserted(changes, key, status):
    section = build_legal_section(context(**changes), draft(ref()))
    assert {r.key: r.status for r in section.requirements}[key] is status
    assert any("requisitos cumulativos" in w for w in section.warnings)


def test_evidence_requirement_depends_on_confirmed_high_level_supporting_studies():
    check = lambda d: {r.key: r for r in build_legal_section(context(), d).requirements}["evidencia"]
    assert check(draft(ref(types=("Journal Article", "Systematic Review")))).status is RequirementStatus.MET
    assert check(draft(ref(types=("Journal Article", "Case Reports")))).status is RequirementStatus.NOT_MET
    assert check(draft(ref(direction=SupportDirection.OPPOSING))).status is RequirementStatus.PENDING
    guideline = check(draft(ref(types=("Practice Guideline",))))
    assert guideline.status is RequirementStatus.NOT_MET and "1 diretriz" in guideline.basis


def test_in_rol_urgency_self_managed_and_opposing_evidence():
    section = build_legal_section(context(rol_status=RolStatus.IN_ROL, urgency=Urgency.EMERGENCY, self_managed_plan=True,
                                         prior_request_to_operator=None),
                                  draft(ref(), ref(2, SupportDirection.OPPOSING)))
    text = render_legal_markdown(section)
    assert section.requirements == () and "§ 12" in text and "emergência" in text and "art. 35-C" in text
    assert "CDC não se aplica" in text and "cdc-art47" not in [s.source_id for s in section.sources]
    assert "1 evidência(s) contrária(s)" in text and any("pedido prévio" in w for w in section.warnings)


def test_unknown_rol_status_is_a_warning_and_procedure_is_required():
    section = build_legal_section(context(rol_status=RolStatus.UNKNOWN, self_managed_plan=None), draft(ref()))
    assert any("consta do Rol" in w for w in section.warnings)
    assert "confirmar que o plano não é de autogestão" in render_legal_markdown(section)
    with pytest.raises(ValueError):
        build_legal_section(context(procedure=" "), draft(ref()))


def test_printable_document_escapes_input_and_leaves_identification_blank():
    hostile = context(procedure='<script>alert(1)</script>', prescriber_registration="CRM <b>")
    page = render_coverage_html(draft(ref()), build_legal_section(hostile, draft(ref())), hostile,
                                "Resumo clínico <img src=x onerror=1>\n\nSegundo parágrafo")
    assert "<script>" not in page and "<img" not in page and "&lt;script&gt;" in page
    assert page.count('class="fill"') >= 4 and "Assinatura e carimbo do médico assistente" in page
    assert "RASCUNHO" in page and "Ref 1." in page and "ensaio clínico randomizado" in page
    assert "<p>Segundo parágrafo</p>" in page
