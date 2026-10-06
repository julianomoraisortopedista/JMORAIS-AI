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

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, Field, SecretStr

from jmoraIs.application.coverage_document import RequestDetails, render_coverage_html
from jmoraIs.application.evidence_packages import ScientificEvidencePackagePort
from jmoraIs.application.evidence_query import EvidenceQueryRejected, PICOQuestion, build_pubmed_query
from jmoraIs.application.legal_basis import (
    AnsAnalysis, CoverageContext, RolStatus, Urgency, build_legal_section, render_legal_markdown,
)
from jmoraIs.application.scientific_justification import JustificationRejected, build_justification, render_markdown
from jmoraIs.application.scientific_verification import AuthoritativeReconciliationPipeline, ScientificVerificationInput
from jmoraIs.application.case_intake import (
    CATEGORY_PT, MAX_DOCUMENT_CHARS, CaseDocument, CaseIntakeRejected, extract_text, prepare_documents,
)
from jmoraIs.application.deidentification import DeidentificationRejected, PatientIdentifiers, deidentify
from jmoraIs.application.question_translation import QuestionTranslationRejected
from jmoraIs.application.report_drafting import ReportDraftRejected
from jmoraIs.application.surgical_catalog import (
    CatalogRejected, CatalogStore, ProcedureTemplate, supplier_warnings, validate_against_tuss,
)
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
MAX_DOCUMENT_B64 = 1_000_000 - 4096  # one file per request, inside the API's 1 MB body limit
MAX_CASE_DOCUMENTS = 8
MIN_RESULTS = 5  # widen the PICO search below this many PubMed records
MAX_IMPORT = 10  # keeps verification inside the platform's 30 s request budget


class SearchIn(BaseModel):
    population: str = Field(max_length=500)
    intervention: str = Field(max_length=500)
    comparison: str = Field("", max_length=500)
    outcome: str = Field("", max_length=500)
    designs: list[str] = Field(default_factory=list, max_length=4)
    since_years: Optional[int] = Field(None, ge=1, le=30)


class ImportIn(BaseModel):
    identifiers: str = Field(min_length=3, max_length=2000)


class PmidIn(BaseModel):
    pmid: str = Field(pattern=r"^[1-9][0-9]{0,8}$")


class KeyIn(BaseModel):
    key: SecretStr = Field(max_length=400)


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


class QuestionIn(BaseModel):
    question: str = Field("", max_length=2000)
    template_id: Optional[str] = Field(None, max_length=40)


class TussIn(BaseModel):
    code: str = Field(pattern=r"^\d{8}$")
    description: str = Field("", max_length=200)


class OpmeIn(BaseModel):
    description: str = Field(min_length=2, max_length=200)
    anvisa: str = Field("", max_length=40)
    quantity: int = Field(1, ge=1, le=50)


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
    case_id: Optional[str] = Field(None, max_length=40)
    template_id: Optional[str] = Field(None, max_length=40)
    tuss: list[TussIn] = Field(default_factory=list, max_length=10)
    opme: list[OpmeIn] = Field(default_factory=list, max_length=20)
    icd10: list[str] = Field(default_factory=list, max_length=8)
    laterality: str = Field("", max_length=40)
    regime: str = Field("", max_length=60)


class WorkbenchAuthError(Exception):
    """Raised by a platform authenticator; status is 401 or 403."""

    def __init__(self, status: int = 401):
        super().__init__("authentication rejected")
        self.status = status


class IdentifiersIn(BaseModel):
    name: str = Field("", max_length=200)
    cpf: str = Field("", max_length=20)
    rg: str = Field("", max_length=20)
    card_number: str = Field("", max_length=40)
    birth_date: str = Field("", max_length=12)
    phone: str = Field("", max_length=20)
    email: str = Field("", max_length=120)
    address: str = Field("", max_length=300)


class CaseIn(BaseModel):
    history: str = Field("", max_length=20000)
    identifiers: IdentifiersIn
    consent: bool


class CaseDocumentIn(BaseModel):
    name: str = Field(max_length=200)
    content_base64: str = Field(max_length=MAX_DOCUMENT_B64)
    identifiers: IdentifiersIn


class ReportIn(BaseModel):
    procedure: str = Field("", max_length=300)
    laterality: str = Field("", max_length=40)
    template_id: Optional[str] = Field(None, max_length=40)
    opme: list[str] = Field(default_factory=list, max_length=20)


class CaseConfirmIn(BaseModel):
    fact_ids: list[str] = Field(default_factory=list, max_length=80)
    edits: dict[str, str] = Field(default_factory=dict)
    icd10: list[str] = Field(default_factory=list, max_length=8)


class WorkbenchState:
    """Mutable per-process session (not a domain object). Holds de-identified text only."""

    def __init__(self) -> None:
        self.proposals: dict = {}   # proposal_id -> SupportClassificationProposal
        self.decisions: dict = {}   # pmid -> decision record (latest physician decision)
        self.cases: dict = {}       # case_id -> dict (de-identified texts, extraction job, confirmed facts)


def _split(value: str) -> tuple[str, ...]:
    return tuple(v.strip() for v in value.split(";") if v.strip())


def create_app(*, pubmed, crossref, classifier_factory: Optional[Callable] = None,
               clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc), token: Optional[str] = None,
               resolve_classifier: Optional[Callable[[], Optional[Callable]]] = None,
               save_key: Optional[Callable[[str], bool]] = None,
               authenticate: Optional[Callable[[Request], str]] = None,
               resolve_case_extractor: Optional[Callable[[], Optional[Callable]]] = None,
               tuss_index=None, catalog: Optional[CatalogStore] = None,
               resolve_question_translator: Optional[Callable[[], Optional[Callable]]] = None,
               resolve_report_writer: Optional[Callable[[], Optional[Callable]]] = None) -> FastAPI:
    """`pubmed`/`crossref` are composed by the entry point (scripts/workbench.py).
    `resolve_classifier` re-checks credentials per request (so a key saved while running
    is picked up); `save_key` stores a pasted key in the macOS Keychain.
    `authenticate` (platform mode) replaces the per-process token: it must validate the
    caller's OIDC bearer through the platform IAM and return the principal id; work
    state is then kept per principal and the standalone page is not served."""
    def current_classifier():
        return resolve_classifier() if resolve_classifier else classifier_factory
    token = token or secrets.token_urlsafe(32)
    states: dict[str, WorkbenchState] = {}

    def state_of(request: Request) -> WorkbenchState:
        return states.setdefault(getattr(request.state, "principal", "local"), WorkbenchState())
    app = FastAPI(title="JMORAIS Workbench", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.token = token

    @app.middleware("http")
    async def guard(request: Request, call_next):
        host = (request.headers.get("host") or "").rsplit(":", 1)[0].strip("[]")
        if host not in ALLOWED_HOSTS:
            return JSONResponse({"detail": "host rejected"}, status_code=403)
        relative = request.url.path[len(request.scope.get("root_path", "")):]
        if relative.startswith("/api/"):
            if authenticate is not None:
                try:
                    request.state.principal = await run_in_threadpool(authenticate, request)
                except WorkbenchAuthError as exc:
                    return JSONResponse({"detail": "Sessão inválida ou sem permissão."}, status_code=exc.status)
            elif not secrets.compare_digest(request.headers.get("x-workbench-token", ""), token):
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

    def reviewer_of(request: Request, crm: str) -> str:
        principal = getattr(request.state, "principal", None)
        return f"{crm.strip()} · {principal}" if principal else crm

    def fetch(pmid: str):
        try:
            return pubmed.fetch_abstract(pmid)
        except AbstractUnavailable as exc:
            bad(f"Resumo indisponível no PubMed: {exc}", 404)

    @app.get("/", response_class=HTMLResponse)
    def index():
        if authenticate is not None:
            bad("Use a plataforma.", 404)
        return PAGE.read_text(encoding="utf-8").replace("__WORKBENCH_TOKEN__", token)

    @app.get("/api/status")
    def status(request: Request):
        return {"model_configured": current_classifier() is not None, "decisions": len(state_of(request).decisions),
                "case_ai": bool(resolve_case_extractor and resolve_case_extractor()),
                "can_save_key": save_key is not None}

    @app.post("/api/search")
    def search(body: SearchIn):
        try:
            from_year = clock().year - body.since_years + 1 if body.since_years else None
            question = PICOQuestion(_split(body.population), _split(body.intervention), _split(body.comparison),
                                    _split(body.outcome), tuple(body.designs), from_year)
        except EvidenceQueryRejected as exc:
            bad(f"Pergunta inválida: {exc}")
        # Progressive widening: drop outcome, then comparison, until at least MIN_RESULTS records exist.
        from dataclasses import replace as _replace
        attempts = [(question, [])]
        if question.outcome:
            attempts.append((_replace(question, outcome=()), ["desfecho"]))
        if question.comparison:
            attempts.append((_replace(question, outcome=(), comparison=()), ["desfecho", "comparação"]))
        built, relaxed = build_pubmed_query(question, pubmed.mesh_headings_for), []
        counter = getattr(pubmed, "count", None)
        if counter is not None:
            for candidate, dropped in attempts:
                candidate_built = build_pubmed_query(candidate, pubmed.mesh_headings_for)
                total = counter(candidate_built.query)
                built, relaxed = candidate_built, dropped
                if total is None or total >= MIN_RESULTS:
                    break
        result = AuthoritativeReconciliationPipeline(pubmed=pubmed, crossref=crossref).discover(
            ScientificVerificationInput(query=built.query))
        return {"query": built.query, "relaxed": relaxed,
                "mesh": [dict(element=e.element, synonym=e.synonym, heading=e.mesh_heading) for e in built.expansions],
                "candidates": [dict(pmid=a.pmid, doi=a.doi, title=a.title) for a in result.articles if a.pmid]}

    @app.post("/api/settings/anthropic-key")
    def store_key(body: KeyIn):
        if save_key is None:
            bad("Configuração de chave indisponível neste computador.", 404)
        if not save_key(body.key.get_secret_value()):
            bad("Chave não aceita. Copie de novo em platform.claude.com (começa com sk-ant-).")
        return {"model_configured": current_classifier() is not None}

    def case_of(request: Request, case_id: str) -> dict:
        case = state_of(request).cases.get(case_id)
        if case is None:
            bad("Caso não encontrado; comece de novo.", 404)
        return case

    def identifiers(body: IdentifiersIn) -> PatientIdentifiers:
        return PatientIdentifiers(**body.model_dump())

    def case_view(case_id: str, case: dict) -> dict:
        job = case["job"]
        return {"case_id": case_id, "history": case["history"].text, "history_removed": case["history"].removed,
                "documents": [dict(label=d.label, name=d_name, text=d.text, removed=d.removed)
                              for d, d_name in case["documents"]],
                "status": job["status"], "error": job.get("error"),
                "facts": [dict(fact_id=f.fact_id, category=f.category.value, category_label=CATEGORY_PT[f.category],
                               statement=f.statement, quote=f.quote, source=f.source) for f in job.get("facts", ())],
                "discarded": job.get("discarded", 0), "icd10_suggestions": list(job.get("icd10", ())),
                "model": job.get("model"), "confirmed": case.get("confirmed"), "report": case.get("report")}

    @app.post("/api/case")
    def case_create(body: CaseIn, request: Request):
        if not body.consent:
            bad("Registre o consentimento do paciente antes de enviar documentos à IA.")
        try:
            history, _ = prepare_documents([], body.history, identifiers(body.identifiers))
        except (CaseIntakeRejected, DeidentificationRejected) as exc:
            bad(str(exc))
        case_id = "case-" + secrets.token_hex(8)
        state_of(request).cases[case_id] = {"history": history, "documents": [], "job": {"status": "NEW"}}
        return case_view(case_id, state_of(request).cases[case_id])

    @app.post("/api/case/{case_id}/document")
    def case_document(case_id: str, body: CaseDocumentIn, request: Request):
        import base64
        case = case_of(request, case_id)
        if len(case["documents"]) >= MAX_CASE_DOCUMENTS:
            bad(f"Máximo de {MAX_CASE_DOCUMENTS} documentos por caso.")
        try:
            content = base64.b64decode(body.content_base64, validate=True)
        except ValueError:
            bad("Arquivo inválido.")
        try:
            text = extract_text(body.name, content)[:MAX_DOCUMENT_CHARS]
            cleaned = deidentify(text, identifiers(body.identifiers))
        except (CaseIntakeRejected, DeidentificationRejected) as exc:
            bad(str(exc))
        label = f"Documento {len(case['documents']) + 1}"
        case["documents"].append((CaseDocument(label, cleaned.text, cleaned.removed), body.name[:120]))
        case["job"] = {"status": "NEW"}
        return case_view(case_id, case)

    @app.post("/api/case/{case_id}/extract")
    def case_extract(case_id: str, request: Request):
        case = case_of(request, case_id)
        factory = resolve_case_extractor() if resolve_case_extractor else None
        if factory is None:
            bad("Modelo de IA não configurado.", 503)
        if case["job"]["status"] == "RUNNING":
            return case_view(case_id, case)
        case["job"] = {"status": "RUNNING"}
        principal = getattr(request.state, "principal", "local")

        def run():
            try:
                with TenantContextBinder().bind_tenant(tenant(principal)):
                    result = factory().extract(case["history"], tuple(d for d, _ in case["documents"]))
                case["job"] = {"status": result.status, "facts": result.facts, "discarded": result.discarded,
                               "icd10": result.icd10_suggestions, "model": result.model_id}
            except CaseIntakeRejected as exc:
                case["job"] = {"status": "ERROR", "error": str(exc)}
            except Exception as exc:  # provider failure: no provider text is exposed
                case["job"] = {"status": "ERROR", "error": f"Falha ao consultar o modelo ({type(exc).__name__})."}
        __import__("threading").Thread(target=run, daemon=True).start()
        return case_view(case_id, case)

    @app.get("/api/case/{case_id}")
    def case_get(case_id: str, request: Request):
        return case_view(case_id, case_of(request, case_id))

    @app.post("/api/case/{case_id}/confirm")
    def case_confirm(case_id: str, body: CaseConfirmIn, request: Request):
        import re as _re
        case = case_of(request, case_id)
        facts = {f.fact_id: f for f in case["job"].get("facts", ())}
        unknown = [f for f in body.fact_ids if f not in facts]
        if unknown or not body.fact_ids:
            bad("Selecione fatos válidos extraídos deste caso.")
        codes = [c.strip().upper() for c in body.icd10]
        if any(not _re.fullmatch(r"[A-Z]\d{2}(\.\d{1,2})?", c) for c in codes):
            bad("CID-10 inválido.")
        confirmed = []
        for fid in body.fact_ids:
            fact, edit = facts[fid], " ".join(str(body.edits.get(fid, "")).split())[:400]
            confirmed.append(dict(category=fact.category.value, category_label=CATEGORY_PT[fact.category],
                                  statement=edit or fact.statement, edited=bool(edit and edit != fact.statement),
                                  quote=fact.quote, source=fact.source))
        case["confirmed"] = {"facts": confirmed, "icd10": codes,
                             "reviewer": getattr(request.state, "principal", "local"), "at": clock().isoformat()}
        return case_view(case_id, case)

    @app.post("/api/case/{case_id}/report")
    def case_report(case_id: str, body: ReportIn, request: Request):
        case = case_of(request, case_id)
        confirmed = case.get("confirmed")
        if not confirmed:
            bad("Confirme os fatos clínicos antes de redigir o relatório.")
        factory = resolve_report_writer() if resolve_report_writer else None
        if factory is None:
            bad("Modelo de IA não configurado.", 503)
        parts = [f"Procedimento: {body.procedure.strip()}" if body.procedure.strip() else ""]
        if body.laterality.strip():
            parts.append(f"Lateralidade: {body.laterality.strip()}")
        if confirmed.get("icd10"):
            parts.append("CID-10 confirmados: " + ", ".join(confirmed["icd10"]))
        opme = [o.strip() for o in body.opme if o.strip()]
        if body.template_id:
            template = next((t for t in need_catalog().load() if t.template_id == body.template_id), None)
            if template is not None:
                parts.append("TUSS: " + "; ".join(f"{c} {template.tuss_terms.get(c, '')}" for c in template.tuss_codes))
                opme = [f"{i.quantity}x {i.description}" for i in template.opme] + opme
        if opme:
            parts.append("OPME: " + ", ".join(opme))
        context = ". ".join(p for p in parts if p)
        if case.get("report", {}).get("status") == "RUNNING":
            return case_view(case_id, case)
        case["report"] = {"status": "RUNNING"}
        principal = getattr(request.state, "principal", "local")

        def run():
            try:
                with TenantContextBinder().bind_tenant(tenant(principal)):
                    draft = factory().draft(list(confirmed["facts"]), context)
                case["report"] = {"status": "READY", "dropped": draft.dropped, "gaps": list(draft.gaps), "model": draft.model_id,
                                  "sections": [dict(key=k, title=t, sentences=[dict(text=x.text, fact_ids=list(x.fact_ids)) for x in ss])
                                               for k, t, ss in draft.sections]}
            except ReportDraftRejected as exc:
                case["report"] = {"status": "ERROR", "error": str(exc)}
            except Exception as exc:  # provider failure: no provider text exposed
                case["report"] = {"status": "ERROR", "error": f"Falha ao consultar o modelo ({type(exc).__name__})."}
        __import__("threading").Thread(target=run, daemon=True).start()
        return case_view(case_id, case)

    @app.delete("/api/case/{case_id}")
    def case_delete(case_id: str, request: Request):
        state_of(request).cases.pop(case_id, None)
        return {"deleted": case_id}

    def entry(e) -> dict:
        return dict(code=e.code, term=e.term, active=e.active, model=e.model, manufacturer=e.manufacturer,
                    anvisa=e.anvisa, risk_class=e.risk_class, technical_name=e.technical_name)

    def need_index():
        if tuss_index is None:
            bad("Tabela TUSS oficial não instalada neste servidor (make tuss-index).", 503)
        return tuss_index

    @app.get("/api/tuss/procedures")
    def tuss_procedures(q: str = Query(min_length=2, max_length=120)):
        return {"version": need_index().version(), "results": [entry(e) for e in need_index().procedures(q, 25)]}

    @app.get("/api/tuss/materials")
    def tuss_materials(q: str = Query(min_length=2, max_length=120), manufacturer: str = Query("", max_length=80)):
        return {"version": need_index().version(),
                "results": [entry(e) for e in need_index().materials(q, manufacturer, 40)]}

    def need_catalog() -> CatalogStore:
        if catalog is None:
            bad("Base de modelos indisponível neste servidor.", 503)
        return catalog

    @app.get("/api/catalog")
    def catalog_list():
        return {"templates": [dict(t.model_dump(), warnings=supplier_warnings(t)) for t in need_catalog().load()],
                "tuss_version": tuss_index.version() if tuss_index else None}

    @app.put("/api/catalog")
    def catalog_save(body: ProcedureTemplate):
        try:
            saved = need_catalog().save(validate_against_tuss(body, need_index()))
        except CatalogRejected as exc:
            bad(str(exc))
        return dict(saved.model_dump(), warnings=supplier_warnings(saved))

    @app.delete("/api/catalog/{template_id}")
    def catalog_delete(template_id: str):
        need_catalog().delete(template_id)
        return {"deleted": template_id}

    @app.post("/api/question")
    def question(body: QuestionIn, request: Request):
        factory = resolve_question_translator() if resolve_question_translator else None
        if factory is None:
            bad("Modelo de IA não configurado. Preencha os campos PICO em inglês.", 503)
        context = ""
        if body.template_id:
            template = next((t for t in need_catalog().load() if t.template_id == body.template_id), None)
            if template is None:
                bad("Modelo não encontrado.", 404)
            materials = sorted({m.term for s in template.suppliers for m in s.materials})
            context = (f"Procedimento: {template.name}. TUSS: " + "; ".join(f"{c} {template.tuss_terms.get(c, '')}" for c in template.tuss_codes)
                       + (". OPME: " + ", ".join(f"{i.quantity}x {i.description}" for i in template.opme) if template.opme else "")
                       + (". Materiais: " + "; ".join(materials[:6]) if materials else ""))
        try:
            with TenantContextBinder().bind_tenant(tenant(getattr(request.state, "principal", "local"))):
                draft = factory().translate(body.question, context)
        except QuestionTranslationRejected as exc:
            bad(str(exc))
        except Exception as exc:  # provider failure: no provider text exposed
            bad(f"Falha ao consultar o modelo ({type(exc).__name__}).", 502)
        return {"claim": draft.claim, "population": list(draft.population), "intervention": list(draft.intervention),
                "comparison": list(draft.comparison), "outcome": list(draft.outcome), "designs": list(draft.designs),
                "model": draft.model_id, "context": context}

    @app.post("/api/import")
    def import_identifiers(body: ImportIn):
        """PMIDs/DOIs the physician found elsewhere (e.g. read in a subscription service)."""
        import re
        tokens = [t.strip().rstrip(".,;") for t in re.split(r"[\s,;]+", body.identifiers) if t.strip()]
        if not tokens or len(tokens) > MAX_IMPORT:
            bad(f"Informe de 1 a {MAX_IMPORT} PMIDs ou DOIs.")
        requests_, invalid = [], []
        for token in dict.fromkeys(tokens):
            doi = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:)", "", token, flags=re.I)
            if re.fullmatch(r"[1-9][0-9]{0,8}", token):
                requests_.append(ScientificVerificationInput(pmid=token))
            elif re.fullmatch(r"10\.\d{4,9}/\S{1,200}", doi):
                requests_.append(ScientificVerificationInput(doi=doi))
            else:
                invalid.append(token[:40])
        pipeline = AuthoritativeReconciliationPipeline(pubmed=pubmed, crossref=crossref)
        found, seen = [], set()
        for request in requests_:
            for article in pipeline.discover(request).articles:
                if article.pmid and article.pmid not in seen:
                    seen.add(article.pmid)
                    found.append(dict(pmid=article.pmid, doi=article.doi, title=article.title))
        return {"candidates": found, "invalid": invalid}

    @app.post("/api/abstract")
    def abstract(body: PmidIn):
        value = fetch(body.pmid)
        return {"pmid": value.pmid, "title": value.title, "text": value.text, "url": value.source_locator}

    def proposal_out(request, proposal):
        state_of(request).proposals[proposal.proposal_id] = proposal
        return {"proposal_id": proposal.proposal_id, "pmid": proposal.pmid, "status": proposal.status.value,
                "direction": proposal.proposed_direction.value if proposal.proposed_direction else None,
                "quote": proposal.quote, "rationale": proposal.rationale, "model": proposal.model_id}

    @app.post("/api/propose")
    def propose(body: ProposeIn, request: Request):
        factory = current_classifier()
        if factory is None:
            bad("Modelo de IA não configurado (ANTHROPIC_API_KEY). Use a classificação manual.", 503)
        value = fetch(body.pmid)
        service = factory()
        try:
            with TenantContextBinder().bind_tenant(tenant("workbench")):
                return proposal_out(request, service.propose(body.claim, value))
        except SupportClassificationRejected as exc:
            bad(str(exc))
        except Exception as exc:  # provider failures: no provider text is exposed
            bad(f"Falha ao consultar o modelo ({type(exc).__name__}). Tente de novo ou classifique manualmente.", 502)

    @app.post("/api/manual")
    def manual(body: ManualIn, request: Request):
        value = fetch(body.pmid)
        try:
            proposal = manual_proposal(body.claim, value, body.direction, body.quote, clock=clock)
            decision = decide_proposal(proposal, reviewer_id=reviewer_of(request, body.reviewer),
                                       decision=PhysicianDecisionType.ACCEPT, clock=clock)
        except SupportClassificationRejected as exc:
            bad("O trecho precisa ser copiado literalmente do resumo (mínimo de 20 caracteres)."
                if "verbatim" in str(exc) else str(exc))
        record = decision_record(decision)
        state_of(request).decisions[body.pmid] = record
        return record

    @app.post("/api/decide")
    def decide(body: DecideIn, request: Request):
        proposal = state_of(request).proposals.get(body.proposal_id)
        if proposal is None:
            bad("Sugestão não encontrada; gere de novo.", 404)
        try:
            decision = decide_proposal(proposal, reviewer_id=reviewer_of(request, body.reviewer), decision=body.decision,
                                       final_direction=body.final_direction, note=body.note, clock=clock)
        except SupportClassificationRejected as exc:
            bad(str(exc))
        record = decision_record(decision)
        state_of(request).decisions[proposal.pmid] = record
        return record

    @app.get("/api/decisions")
    def decisions(request: Request):
        return list(state_of(request).decisions.values())

    @app.delete("/api/decisions/{pmid}")
    def remove(pmid: str, request: Request):
        state_of(request).decisions.pop(pmid, None)
        return {"removed": pmid}

    @app.post("/api/document")
    def document(body: DocumentIn, request: Request):
        claim = " ".join(body.claim.split())
        records = [r for r in state_of(request).decisions.values() if " ".join(r["claim"].split()) == claim]
        packages = ScientificEvidencePackagePort(catalog=InMemoryPackageCatalogRepository(), clock=clock)
        pipeline = AuthoritativeReconciliationPipeline(pubmed=pubmed, crossref=crossref, packages=packages, clock=clock)
        try:
            draft = build_justification(claim, records, pubmed=pubmed, pipeline=pipeline, packages=packages, clock=clock)
            context = CoverageContext(body.procedure, body.rol, body.urgency, body.ans_analysis, body.no_rol_alternative,
                                      body.anvisa, body.crm, body.prior_request, body.autogestao,
                                      bool(body.opme or body.template_id))
            legal = build_legal_section(context, draft)
        except (JustificationRejected, ValueError) as exc:
            bad(str(exc))
        facts, codes = (), [c.strip().upper() for c in body.icd10]
        if body.case_id:
            confirmed = (case_of(request, body.case_id).get("confirmed") or {})
            if not confirmed:
                bad("Confirme os fatos clínicos do caso antes de gerar o pedido.")
            facts = tuple(confirmed["facts"])
            codes = list(dict.fromkeys(confirmed["icd10"] + codes))
        tuss = [(t.code, t.description) for t in body.tuss]
        opme = [(o.description, o.anvisa, o.quantity) for o in body.opme]
        brands, regime = (), body.regime.strip()
        if body.template_id:
            template = next((t for t in need_catalog().load() if t.template_id == body.template_id), None)
            if template is None:
                bad("Modelo não encontrado.", 404)
            if not template.codes_confirmed:
                bad("Confirme os códigos TUSS do modelo antes de usá-lo num pedido.")
            tuss = [(c, template.tuss_terms.get(c, "")) for c in template.tuss_codes] + [t for t in tuss if t[0] not in template.tuss_codes]
            opme = [(i.description, "ver marcas indicadas", i.quantity) for i in template.opme] + opme
            brands = tuple((s.label, tuple((template.opme[m.item_index].description, template.opme[m.item_index].quantity,
                                            m.term, m.manufacturer, m.anvisa, m.tuss_code) for m in s.materials))
                           for s in template.suppliers if s.materials)
            regime = regime or template.regime
        try:
            details = RequestDetails(tuple(codes), tuple(tuss), tuple(opme), body.laterality.strip(), regime, brands)
        except ValueError as exc:
            bad(str(exc))
        has_details = bool(codes or tuss or opme or body.laterality or regime)
        return {"html": render_coverage_html(draft, legal, context, body.clinical_summary,
                                             details if has_details else None, facts),
                "markdown": render_markdown(draft) + "\n" + render_legal_markdown(legal),
                "included": len(draft.references), "excluded": [dict(pmid=e.pmid, reason=e.reason) for e in draft.excluded],
                "warnings": list(legal.warnings),
                "requirements": [dict(label=r.label, status=r.status.value, basis=r.basis) for r in legal.requirements]}

    return app


def default_classifier_factory(environ=os.environ, keychain=None) -> Optional[Callable]:
    from jmoraIs.application.support_classification_runtime import build_service, credentials_configured, keychain_api_key
    return build_service if credentials_configured(environ, keychain=keychain or keychain_api_key) else None


def default_case_extractor_factory(environ=os.environ, keychain=None) -> Optional[Callable]:
    from jmoraIs.application.support_classification_runtime import (
        build_case_extraction_service, credentials_configured, keychain_api_key,
    )
    return build_case_extraction_service if credentials_configured(environ, keychain=keychain or keychain_api_key) else None


def default_question_translator_factory(environ=os.environ, keychain=None) -> Optional[Callable]:
    from jmoraIs.application.support_classification_runtime import (
        build_question_service, credentials_configured, keychain_api_key,
    )
    return build_question_service if credentials_configured(environ, keychain=keychain or keychain_api_key) else None


def default_report_writer_factory(environ=os.environ, keychain=None) -> Optional[Callable]:
    from jmoraIs.application.support_classification_runtime import build_report_service, credentials_configured, keychain_api_key
    return build_report_service if credentials_configured(environ, keychain=keychain or keychain_api_key) else None
