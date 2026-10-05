"""Local physician workbench: search -> classify -> confirm -> coverage document.

A single-user ASGI app for the physician's own computer. It binds to loopback only,
rejects foreign Host headers (DNS rebinding) and requires a per-process random token
on every API call (no cookies, no CORS), so other web pages cannot drive it. All
domain rules live in the existing modules; proposals and decisions are kept server-
side so the browser cannot forge a physician decision. State is in memory: export
decisions to keep them. No patient identifiers are requested or stored.
"""
from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import secrets
from typing import Callable, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from jmoraIs.application.coverage_document import render_coverage_html
from jmoraIs.application.evidence_packages import ScientificEvidencePackagePort
from jmoraIs.application.evidence_query import EvidenceQueryRejected, PICOQuestion, build_pubmed_query
from jmoraIs.application.legal_basis import (
    AnsAnalysis, CoverageContext, RolStatus, Urgency, build_legal_section, render_legal_markdown,
)
from jmoraIs.application.scientific_justification import JustificationRejected, build_justification, render_markdown
from jmoraIs.application.scientific_verification import AuthoritativeReconciliationPipeline, ScientificVerificationInput
from jmoraIs.application.support_classification import (
    AbstractUnavailable, PhysicianDecisionType, SupportClassificationRejected, decide_proposal, decision_record,
    manual_proposal,
)
from jmoraIs.infrastructure import InMemoryPackageCatalogRepository
from jmoraIs.scientific_domain import SupportDirection
from jmoraIs.tenancy.context import TenantContextBinder
from jmoraIs.tenancy.domain import TenantContext

PAGE = Path(__file__).with_name("index.html")
ALLOWED_HOSTS = ("127.0.0.1", "localhost")


class SearchIn(BaseModel):
    population: str = Field(max_length=500)
    intervention: str = Field(max_length=500)
    comparison: str = Field("", max_length=500)
    outcome: str = Field("", max_length=500)
    designs: list[str] = Field(default_factory=list, max_length=4)


class PmidIn(BaseModel):
    pmid: str = Field(pattern=r"^[1-9][0-9]{0,8}$")


class ProposeIn(PmidIn):
    claim: str = Field(min_length=10, max_length=600)


class ManualIn(ProposeIn):
    direction: SupportDirection
    quote: str = Field(min_length=20, max_length=2000)
    reviewer: str = Field(min_length=3, max_length=60)


class DecideIn(BaseModel):
    proposal_id: str = Field(max_length=80)
    decision: PhysicianDecisionType
    final_direction: Optional[SupportDirection] = None
    note: str = Field("", max_length=1000)
    reviewer: str = Field(min_length=3, max_length=60)


class DocumentIn(BaseModel):
    claim: str = Field(min_length=10, max_length=600)
    procedure: str = Field(min_length=3, max_length=300)
    rol: RolStatus = RolStatus.UNKNOWN
    urgency: Urgency = Urgency.ELECTIVE
    ans_analysis: AnsAnalysis = AnsAnalysis.UNKNOWN
    no_rol_alternative: str = Field("", max_length=1500)
    anvisa: str = Field("", max_length=120)
    crm: str = Field("", max_length=60)
    prior_request: Optional[bool] = None
    autogestao: Optional[bool] = None
    clinical_summary: str = Field("", max_length=8000)


class WorkbenchState:
    """Mutable per-process session (not a domain object)."""

    def __init__(self) -> None:
        self.proposals: dict = {}   # proposal_id -> SupportClassificationProposal
        self.decisions: dict = {}   # pmid -> decision record (latest physician decision)


def _split(value: str) -> tuple[str, ...]:
    return tuple(v.strip() for v in value.split(";") if v.strip())


def create_app(*, pubmed, crossref, classifier_factory: Optional[Callable] = None,
               clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc), token: Optional[str] = None) -> FastAPI:
    """`pubmed`/`crossref` are composed by the entry point (scripts/workbench.py)."""
    token = token or secrets.token_urlsafe(32)
    state = WorkbenchState()
    app = FastAPI(title="JMORAIS Workbench", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.token = token

    @app.middleware("http")
    async def guard(request: Request, call_next):
        host = (request.headers.get("host") or "").rsplit(":", 1)[0].strip("[]")
        if host not in ALLOWED_HOSTS:
            return JSONResponse({"detail": "host rejected"}, status_code=403)
        if request.url.path.startswith("/api/") and not secrets.compare_digest(
                request.headers.get("x-workbench-token", ""), token):
            return JSONResponse({"detail": "token required"}, status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        return response

    def bad(message: str, status: int = 400):
        raise HTTPException(status_code=status, detail=message)

    def tenant(reviewer: str) -> TenantContext:
        return TenantContext("local-physician", "local-org", reviewer, "CLINICIAN", "CLINICAL_DOCUMENTATION",
                             "ST-02", "corr-workbench-" + secrets.token_hex(8))

    def fetch(pmid: str):
        try:
            return pubmed.fetch_abstract(pmid)
        except AbstractUnavailable as exc:
            bad(f"Resumo indisponível no PubMed: {exc}", 404)

    @app.get("/", response_class=HTMLResponse)
    def index():
        return PAGE.read_text(encoding="utf-8").replace("__WORKBENCH_TOKEN__", token)

    @app.get("/api/status")
    def status():
        return {"model_configured": classifier_factory is not None, "decisions": len(state.decisions)}

    @app.post("/api/search")
    def search(body: SearchIn):
        try:
            question = PICOQuestion(_split(body.population), _split(body.intervention), _split(body.comparison),
                                    _split(body.outcome), tuple(body.designs))
        except EvidenceQueryRejected as exc:
            bad(f"Pergunta inválida: {exc}")
        built = build_pubmed_query(question, pubmed.mesh_headings_for)
        result = AuthoritativeReconciliationPipeline(pubmed=pubmed, crossref=crossref).discover(
            ScientificVerificationInput(query=built.query))
        return {"query": built.query,
                "mesh": [dict(element=e.element, synonym=e.synonym, heading=e.mesh_heading) for e in built.expansions],
                "candidates": [dict(pmid=a.pmid, doi=a.doi, title=a.title) for a in result.articles if a.pmid]}

    @app.post("/api/abstract")
    def abstract(body: PmidIn):
        value = fetch(body.pmid)
        return {"pmid": value.pmid, "title": value.title, "text": value.text, "url": value.source_locator}

    def proposal_out(proposal):
        state.proposals[proposal.proposal_id] = proposal
        return {"proposal_id": proposal.proposal_id, "pmid": proposal.pmid, "status": proposal.status.value,
                "direction": proposal.proposed_direction.value if proposal.proposed_direction else None,
                "quote": proposal.quote, "rationale": proposal.rationale, "model": proposal.model_id}

    @app.post("/api/propose")
    def propose(body: ProposeIn):
        if classifier_factory is None:
            bad("Modelo de IA não configurado (ANTHROPIC_API_KEY). Use a classificação manual.", 503)
        value = fetch(body.pmid)
        service = classifier_factory()
        try:
            with TenantContextBinder().bind_tenant(tenant("workbench")):
                return proposal_out(service.propose(body.claim, value))
        except SupportClassificationRejected as exc:
            bad(str(exc))
        except Exception as exc:  # provider failures: no provider text is exposed
            bad(f"Falha ao consultar o modelo ({type(exc).__name__}). Tente de novo ou classifique manualmente.", 502)

    @app.post("/api/manual")
    def manual(body: ManualIn):
        value = fetch(body.pmid)
        try:
            proposal = manual_proposal(body.claim, value, body.direction, body.quote, clock=clock)
            decision = decide_proposal(proposal, reviewer_id=body.reviewer, decision=PhysicianDecisionType.ACCEPT,
                                       clock=clock)
        except SupportClassificationRejected as exc:
            bad("O trecho precisa ser copiado literalmente do resumo (mínimo de 20 caracteres)."
                if "verbatim" in str(exc) else str(exc))
        record = decision_record(decision)
        state.decisions[body.pmid] = record
        return record

    @app.post("/api/decide")
    def decide(body: DecideIn):
        proposal = state.proposals.get(body.proposal_id)
        if proposal is None:
            bad("Sugestão não encontrada; gere de novo.", 404)
        try:
            decision = decide_proposal(proposal, reviewer_id=body.reviewer, decision=body.decision,
                                       final_direction=body.final_direction, note=body.note, clock=clock)
        except SupportClassificationRejected as exc:
            bad(str(exc))
        record = decision_record(decision)
        state.decisions[proposal.pmid] = record
        return record

    @app.get("/api/decisions")
    def decisions():
        return list(state.decisions.values())

    @app.delete("/api/decisions/{pmid}")
    def remove(pmid: str):
        state.decisions.pop(pmid, None)
        return {"removed": pmid}

    @app.post("/api/document")
    def document(body: DocumentIn):
        claim = " ".join(body.claim.split())
        records = [r for r in state.decisions.values() if " ".join(r["claim"].split()) == claim]
        packages = ScientificEvidencePackagePort(catalog=InMemoryPackageCatalogRepository(), clock=clock)
        pipeline = AuthoritativeReconciliationPipeline(pubmed=pubmed, crossref=crossref, packages=packages, clock=clock)
        try:
            draft = build_justification(claim, records, pubmed=pubmed, pipeline=pipeline, packages=packages, clock=clock)
            context = CoverageContext(body.procedure, body.rol, body.urgency, body.ans_analysis, body.no_rol_alternative,
                                      body.anvisa, body.crm, body.prior_request, body.autogestao)
            legal = build_legal_section(context, draft)
        except (JustificationRejected, ValueError) as exc:
            bad(str(exc))
        return {"html": render_coverage_html(draft, legal, context, body.clinical_summary),
                "markdown": render_markdown(draft) + "\n" + render_legal_markdown(legal),
                "included": len(draft.references), "excluded": [dict(pmid=e.pmid, reason=e.reason) for e in draft.excluded],
                "warnings": list(legal.warnings),
                "requirements": [dict(label=r.label, status=r.status.value, basis=r.basis) for r in legal.requirements]}

    return app


def default_classifier_factory(environ=os.environ) -> Optional[Callable]:
    from jmoraIs.application.support_classification_runtime import build_service, credentials_configured
    return build_service if credentials_configured(environ) else None
