from jmoraIs.tenancy.context import TenantContextBinder
from tests.test_appeals import DENIAL, service
from tests.test_report_drafting import TENANT

EVIDENCE = (dict(number=1, quote="Genicular nerve block reduced pain and disability in knee osteoarthritis.", direction="SUPPORTING",
                 study="Ensaio clínico randomizado", vancouver="Autor A. Título. Revista. 2026;1:1-2."),)


def test_contestation_cites_the_request_sent_and_verified_articles_with_markers():
    out = {"sections": [{"section": "clinico", "sentences": [
        {"text": "O paciente fez fisioterapia por 20 meses sem melhora.", "source_ids": ["R1"]},
        {"text": "O bloqueio genicular reduziu dor e incapacidade em ensaio randomizado.", "source_ids": ["E1"]},
        {"text": "O bloqueio cura a artrose em 90% dos casos.", "source_ids": ["E1"]}]}], "gaps": []}
    svc, adapter = service(out)
    with TenantContextBinder().bind_tenant(TENANT):
        draft = svc.draft(kind="NEGATIVA", denial_text=DENIAL.replace("123.456.789-09", "[CPF REMOVIDO]"), facts=[], context="",
                          sbot="", examples=[], request_text="Paciente fez fisioterapia por 20 meses sem melhora. Dor EVA 8.",
                          evidence=EVIDENCE)
    texts = [s.text for k, _, ss in draft.sections if k == "clinico" for s in ss]
    assert texts == ["O paciente fez fisioterapia por 20 meses sem melhora.",
                     "O bloqueio genicular reduziu dor e incapacidade em ensaio randomizado. [1]"]
    assert draft.dropped == 1 and draft.sources["E1"].startswith("Autor A.") and draft.sources["R1"].startswith("Pedido enviado")
    payload = adapter.requests[0].canonical_payload
    assert "R1" in payload and "E1" in payload and "qualidade de vida" not in DENIAL


def test_courtesy_and_transitions_flow_but_claims_still_need_sources():
    out = {"sections": [
        {"section": "abertura", "sentences": [
            {"text": "Agradeço a atenção dedicada ao caso e a disposição para o diálogo.", "source_ids": []},
            {"text": "O procedimento é eficaz e seguro.", "source_ids": []},                      # claim without source
            {"text": "Em 90% dos casos há melhora.", "source_ids": []}]},                         # number without source
        {"section": "proposta", "sentences": [
            {"text": "Proponho, em espírito de consenso, as alternativas a seguir.", "source_ids": []},
            {"text": "Conforme a RN 424, a escolha é do médico.", "source_ids": []},             # norm without source
            {"text": "Sigo à disposição para esclarecer o que for necessário.", "source_ids": []},
            {"text": "Uma terceira frase de cortesia na mesma seção.", "source_ids": []}]}],     # over the per-section cap
        "gaps": []}
    svc, _ = service(out)
    with TenantContextBinder().bind_tenant(TENANT):
        draft = svc.draft(kind="NEGATIVA", denial_text=DENIAL.replace("123.456.789-09", "[CPF REMOVIDO]"), facts=[], context="",
                          sbot="", examples=[])
    text = {k: [s.text for s in ss] for k, _, ss in draft.sections}
    assert text["abertura"] == ["Agradeço a atenção dedicada ao caso e a disposição para o diálogo."]
    assert text["proposta"] == ["Proponho, em espírito de consenso, as alternativas a seguir.",
                                "Sigo à disposição para esclarecer o que for necessário."]
    assert draft.dropped == 4
