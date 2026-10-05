from dataclasses import replace
from datetime import datetime, timezone
import json

import pytest

from jmoraIs.application.support_classification import (
    PhysicianDecisionType, ProposalStatus, SupportClassificationRejected, SupportClassificationService,
    register_confirmed_support, support_classification_prompt,
)
from jmoraIs.connect.pubmed import AbstractUnavailable, PubMedConnector, parse_pubmed_abstract
from jmoraIs.evidence_ledger import AppendOnlyEvidenceLedger
from jmoraIs.llm_gateway import (
    CanonicalLLMGateway, LLMProvider, MockProviderAdapter, PromptGovernanceService,
)
from jmoraIs.llm_gateway.infrastructure import (
    InMemoryInvocationRepository, InMemoryLLMInvocationContextRepository,
    InMemoryPromptAuditRepository, InMemoryPromptRepository,
)
from jmoraIs.scientific_domain import SupportDirection
from jmoraIs.tenancy.context import TenantContextBinder
from jmoraIs.tenancy.domain import TenantContext
from tests.test_llm_gateway import model, response

NOW = datetime(2026, 10, 5, tzinfo=timezone.utc)
XML = """<?xml version="1.0" ?>
<!DOCTYPE PubmedArticleSet PUBLIC "-//NLM//DTD PubMedArticle//EN" "https://dtd.nlm.nih.gov/x.dtd">
<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID Version="1">26488691</PMID><Article>
<ArticleTitle>A Randomized, Controlled Trial of Total Knee Replacement.</ArticleTitle><Abstract>
<AbstractText Label="RESULTS">The total-knee-replacement group had greater improvement in the KOOS4
 score than the nonsurgical-treatment group.</AbstractText>
<AbstractText Label="CONCLUSIONS">Total knee replacement followed by nonsurgical treatment resulted in
 greater pain relief and functional improvement after 12 months.</AbstractText>
</Abstract></Article></MedlineCitation></PubmedArticle></PubmedArticleSet>"""
QUOTE = "resulted in greater pain relief and functional improvement after 12 months"
CLAIM = "Total knee replacement improves pain and function versus nonsurgical care in knee osteoarthritis"
TENANT = TenantContext("t-1", "org-1", "physician-1", "CLINICIAN", "CLINICAL_DOCUMENTATION", "ST-02", "corr-support-0001")


def abstract():
    return parse_pubmed_abstract("26488691", XML, NOW)


def setup(*outputs):
    prompts, audit = InMemoryPromptRepository(), InMemoryPromptAuditRepository()
    version = PromptGovernanceService(prompts, audit, clock=lambda: NOW).register(support_classification_prompt(), created_by="architect")
    adapter = MockProviderAdapter(tuple(response(output_text=o) if isinstance(o, str) else o for o in outputs))
    invocations = InMemoryInvocationRepository()
    gateway = CanonicalLLMGateway(prompts, audit, invocations, InMemoryLLMInvocationContextRepository(), (adapter,), clock=lambda: NOW)
    ids = iter(f"id{i}" for i in range(100))
    service = SupportClassificationService(gateway, prompt_version_id=version.prompt_version_id,
                                           model=model(LLMProvider.MOCK), clock=lambda: NOW, id_factory=lambda: next(ids))
    return service, adapter, invocations


def propose(output):
    service, adapter, invocations = setup(output)
    with TenantContextBinder().bind_tenant(TENANT):
        return service.propose(CLAIM, abstract()), service, adapter, invocations


def proposal_json(direction="supporting", quote=QUOTE):
    return json.dumps({"direction": direction, "quote": quote, "rationale": "Primary outcome favoured surgery."})


def test_abstract_parser_keeps_exact_text_labels_and_hash():
    value = abstract()
    assert value.title.startswith("A Randomized") and value.text.startswith("RESULTS: The total-knee")
    assert value.source_locator == "https://pubmed.ncbi.nlm.nih.gov/26488691/" and len(value.content_hash) == 64


@pytest.mark.parametrize("xml", [
    '<!DOCTYPE x [<!ENTITY a "b">]><x/>', "<x><<", XML.replace("26488691", "11111111"),
    XML.replace("<AbstractText", "<Other").replace("</AbstractText>", "</Other>"),
])
def test_abstract_parser_fails_closed(xml):
    with pytest.raises(AbstractUnavailable):
        parse_pubmed_abstract("26488691", xml, NOW)


def test_fetch_rejects_malformed_pmid_before_network():
    with pytest.raises(AbstractUnavailable):
        PubMedConnector(object(), min_interval=0).fetch_abstract("1 OR 1")


def test_grounded_proposal_goes_through_gateway_and_awaits_physician():
    proposal, _, adapter, invocations = propose(proposal_json())
    assert proposal.status is ProposalStatus.PENDING_PHYSICIAN_REVIEW
    assert proposal.proposed_direction is SupportDirection.SUPPORTING and proposal.quote == QUOTE
    payload = json.loads(adapter.requests[0].canonical_payload)
    assert [f["name"] for f in payload["fields"]] == ["claim", "pmid", "title", "abstract"]
    assert invocations.history(proposal.request_id)[0].correlation_id == "corr-support-0001"


@pytest.mark.parametrize("output,reason", [
    (proposal_json(quote="Total knee replacement is always superior to any other care"), "verbatim"),
    (proposal_json(quote="12 months"), "verbatim"),
    ("Surgery is better.", "schema"),
    (json.dumps({"direction": "STRONGLY_SUPPORTING", "quote": QUOTE}), "schema"),
])
def test_fabricated_or_malformed_output_is_ungrounded(output, reason):
    proposal, service, _, _ = propose(output)
    assert proposal.status is ProposalStatus.UNGROUNDED and proposal.quote is None and reason in proposal.rationale
    with pytest.raises(SupportClassificationRejected):
        service.decide(proposal, reviewer_id="dr-1", decision=PhysicianDecisionType.ACCEPT)
    rejected = service.decide(proposal, reviewer_id="dr-1", decision=PhysicianDecisionType.REJECT)
    assert not rejected.usable
    with pytest.raises(SupportClassificationRejected):
        register_confirmed_support(rejected, ledger=AppendOnlyEvidenceLedger(), claim_id="c")


def test_refused_output_is_blocked():
    proposal, _, _, _ = propose(response(output_text="no", refused=True))
    assert proposal.status is ProposalStatus.BLOCKED and proposal.proposed_direction is None


def test_quote_matches_across_section_labels_and_whitespace():
    proposal, _, _, _ = propose(proposal_json(quote="greater improvement in the   KOOS4 score"))
    assert proposal.status is ProposalStatus.PENDING_PHYSICIAN_REVIEW


def test_physician_override_needs_new_direction_and_reason():
    proposal, service, _, _ = propose(proposal_json("neutral"))
    for kwargs in (dict(final_direction=SupportDirection.NEUTRAL, note="x"), dict(final_direction=SupportDirection.SUPPORTING)):
        with pytest.raises(SupportClassificationRejected):
            service.decide(proposal, reviewer_id="dr-1", decision=PhysicianDecisionType.OVERRIDE, **kwargs)
    with pytest.raises(SupportClassificationRejected):
        service.decide(proposal, reviewer_id=" ", decision=PhysicianDecisionType.ACCEPT)
    with pytest.raises(SupportClassificationRejected):
        service.decide(proposal, reviewer_id="dr-1", decision=PhysicianDecisionType.ACCEPT, final_direction=SupportDirection.OPPOSING)
    decision = service.decide(proposal, reviewer_id="dr-1", decision=PhysicianDecisionType.OVERRIDE,
                              final_direction=SupportDirection.SUPPORTING, note="Primary endpoint favours surgery")
    assert decision.final_direction is SupportDirection.SUPPORTING and decision.usable


def test_only_confirmed_decision_enters_ledger_with_model_provenance():
    proposal, service, _, _ = propose(proposal_json())
    decision = service.decide(proposal, reviewer_id="dr-1", decision=PhysicianDecisionType.ACCEPT)
    ledger = AppendOnlyEvidenceLedger()
    claim = ledger.create_claim(CLAIM, claim_id="claim-1", created_at=NOW)
    fragment, support, _ = register_confirmed_support(decision, ledger=ledger, claim_id=claim.claim_id, doi="10.1056/NEJMoa1505467")
    assert support.support_direction == "SUPPORTING"
    assert fragment.passage == QUOTE and fragment.pmid == "26488691"
    assert fragment.model_version == "test-model" and fragment.prompt_version == proposal.prompt_version_id
    assert ledger.verify_integrity(claim.claim_id)


def test_claim_and_abstract_integrity_are_required():
    service, _, _ = setup(proposal_json())
    with TenantContextBinder().bind_tenant(TENANT):
        with pytest.raises(SupportClassificationRejected):
            service.propose("short", abstract())
        with pytest.raises(SupportClassificationRejected):
            service.propose(CLAIM, replace(abstract(), text="tampered"))
