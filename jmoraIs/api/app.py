from __future__ import annotations
from .workspace_launch import WorkspaceBootstrapRequest, WorkspaceBootstrapResponse

import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
from time import monotonic
from typing import Any
from uuid import uuid4

from fastapi import Depends, FastAPI, Query, Request, Response
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler

from jmoraIs.clinical_workspace.viewers import ClinicalWorkspace, WorkspaceReadRejected
from jmoraIs.clinical_state.exact_reference import ClinicalStateExactReferenceError
from jmoraIs.tenancy.context import current_tenant_context
from jmoraIs.tenancy.domain import TenantError
from .workspace_schemas import (
    ClinicalSummaryRequest, ClinicalSummaryResponse, TimelineRequest, TimelineResponse, WorkspaceContextResponse,
    EvidenceRequest, EvidenceResponse, ExplainabilityRequest, ExplainabilityResponse,
    MedicalDocumentRequest, MedicalDocumentResponse as WorkspaceDocumentResponse,
    HumanReviewRequest, HumanReviewResponse, AuditDefenseRequest,
    AuditDefenseResponse as WorkspaceDefenseResponse,
)
from jmoraIs.clinical_workspace.remaining import RemainingClinicalWorkspace
from jmoraIs.appraisal.exact_reference import GovernedEvidenceExactReferenceError
from jmoraIs.reasoning_input.exact_reference import ClinicalReasoningInputExactReferenceError
from jmoraIs.medical_documents.exact_reference import MedicalDocumentExactReferenceError
from jmoraIs.llm_human_review.exact_reference import HumanReviewExactReferenceError
from jmoraIs.governed_llm_draft.exact_reference import GovernedLLMDraftExactReferenceError
from jmoraIs.llm_gateway.exact_reference import LLMInvocationExactReferenceError
from jmoraIs.audit_defense.domain import AuditDefenseError

from jmoraIs import __version__
from jmoraIs.appraisal.governed import GovernedEvidence
from jmoraIs.audit_defense.domain import DefensePackage, DefenseStatus
from jmoraIs.audit_defense.ports import AuditDefenseQueryPort
from jmoraIs.clinical.governed import HumanReviewStatus
from jmoraIs.clinical.governed import GovernedEvidenceLifecycleEligibilityPort, GovernedEvidenceQueryPort
from jmoraIs.guideline_engine.domain import GuidelineRecommendationSet
from jmoraIs.guideline_engine.ports import RecommendationRepository
from jmoraIs.medical_documents.domain import DocumentStatus, MedicalDocumentVersion
from jmoraIs.medical_documents.ports import MedicalDocumentQueryPort
from jmoraIs.orthopedic_intelligence.domain import OrthopedicAssessmentSet
from jmoraIs.orthopedic_intelligence.ports import OrthopedicAssessmentRepository
from jmoraIs.reasoning_input.domain import ClinicalReasoningInput, ReasoningReadiness, ReasoningReviewStatus
from jmoraIs.reasoning_input.ports import ClinicalReasoningInputQueryPort
from jmoraIs.identity.domain import IdentityAuthenticationRejected, IdentityAuthorizationRejected

from .schemas import (
    ApiError, AuditDefenseResponse, ClinicalReasoningInputResponse, DefenseArgumentReference,
    DocumentSectionReference, GovernedEvidenceResponse, GuidelineRecommendationSetResponse,
    BuildResponse, HealthResponse, MedicalDocumentResponse, OrthopedicAssessmentSetResponse, PageMetadata,
    ReadinessCheckResponse, ReadinessResponse, RecommendationReference, VersionResponse,
)
from .security import ApiAccessAuditEvent, ApiLogRecord, ApiMetric, CallerContext, CallerCredentials, CallerRole, PurposeOfUse
from .security_infrastructure import AuthenticationRejected
from .security_ports import (
    ApiAccessAuditPort, ApiAuthenticationPort, ApiAuthorizationPort, ApiMetricsPort, ApiReadinessPort,
    ApiStructuredLogPort,
)

API_VERSION = "v1"
PLATFORM_VERSION = __version__
PREFIX = f"/internal/api/{API_VERSION}"
_CORRELATION = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
MAX_REQUEST_BYTES = 1_048_576


class ApiBoundaryError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 409) -> None:
        super().__init__(message); self.code = code; self.status_code = status_code


@dataclass(frozen=True)
class ApiServices:
    reasoning_inputs: ClinicalReasoningInputQueryPort | None = None
    governed_evidence: GovernedEvidenceQueryPort | None = None
    evidence_lifecycle: GovernedEvidenceLifecycleEligibilityPort | None = None
    guideline_recommendations: RecommendationRepository | None = None
    orthopedic_assessments: OrthopedicAssessmentRepository | None = None
    medical_documents: MedicalDocumentQueryPort | None = None
    audit_defenses: AuditDefenseQueryPort | None = None

    def missing(self) -> tuple[str, ...]:
        return tuple(name for name, value in self.__dict__.items() if value is None)


@dataclass(frozen=True)
class ApiOperationalServices:
    authentication: ApiAuthenticationPort
    authorization: ApiAuthorizationPort
    readiness: ApiReadinessPort
    access_audit: ApiAccessAuditPort
    metrics: ApiMetricsPort
    structured_log: ApiStructuredLogPort
    tenant_context: Any | None = None
    build_metadata: Any | None = None


def _page(items: tuple[Any, ...], offset: int, limit: int) -> tuple[tuple[Any, ...], PageMetadata]:
    selected = items[offset:offset + limit]
    return selected, PageMetadata(offset=offset, limit=limit, returned=len(selected), total=len(items))


def _required(value: Any, expected: type, name: str) -> Any:
    if value is None: raise ApiBoundaryError("NOT_FOUND", f"{name} was not found", 404)
    if not isinstance(value, expected): raise ApiBoundaryError("TRUST_BOUNDARY_REJECTED", f"{name} port returned an invalid type")
    return value


def _approved(status: Any, name: str) -> None:
    if status is not HumanReviewStatus.APPROVED_BY_REVIEWER:
        raise ApiBoundaryError("REVIEW_REQUIRED", f"{name} has not completed canonical reviewer governance")


def create_app(services: ApiServices, operations: ApiOperationalServices, *, runtime_security=None,
               lifespan=None, workspace: ClinicalWorkspace | None = None,
               remaining_workspace: RemainingClinicalWorkspace | None = None, launch_service=None) -> FastAPI:
    app = FastAPI(title="JMORAIS-AI Internal API", version=API_VERSION,
                  description="Internal development adapter only. External, patient-care and production use are prohibited.",
                  openapi_url=f"{PREFIX}/openapi.json", docs_url=f"{PREFIX}/docs", redoc_url=None,
                  lifespan=lifespan)

    workspace_paths = {f"{PREFIX}/workspace/{name}/resolve" for name in
                       ("summary", "timeline", "evidence", "explainability",
                        "medical-document", "human-review", "audit-defense")}

    workspace_paths.add(f"{PREFIX}/workspace/context")

    @app.middleware("http")
    async def correlation_id(request: Request, call_next):
        started = monotonic()
        supplied = request.headers.get("x-correlation-id", "")
        correlation = supplied if _CORRELATION.fullmatch(supplied) else uuid4().hex
        request.state.correlation_id = correlation
        request.state.caller = None
        content_length = request.headers.get("content-length")
        if content_length and (not content_length.isdigit() or int(content_length) > MAX_REQUEST_BYTES):
            body = ApiError(code="REQUEST_TOO_LARGE", message="request exceeds internal API limit",
                            correlation_id=correlation)
            response = JSONResponse(status_code=413, content=body.model_dump(mode="json"))
        else:
            response = await call_next(request)
        response.headers["x-correlation-id"] = correlation
        response.headers["x-jmorais-intended-use"] = "internal-development-only"
        duration = round((monotonic() - started) * 1000, 3)
        route = getattr(request.scope.get("route"), "path", "UNMATCHED")
        caller = request.state.caller
        now = datetime.now(timezone.utc)
        operations.metrics.observe(ApiMetric(route, request.method, response.status_code, duration, now))
        event = ApiAccessAuditEvent(
            event_id="api_" + sha256(
                f"{correlation}|{route}|{request.method}|{response.status_code}|{now.isoformat()}".encode()
            ).hexdigest(),
            caller_id=caller.caller_id if caller else "UNAUTHENTICATED",
            role=caller.role.value if caller else "UNAUTHENTICATED",
            purpose=caller.purpose.value if caller else "UNSPECIFIED",
            correlation_id=correlation, policy_version=caller.policy_version if caller else "api-access-v1",
            route_template=route, method=request.method,
            outcome="ALLOWED" if response.status_code < 400 else "DENIED",
            status_code=response.status_code, duration_ms=duration, occurred_at=now,
            tenant_id=caller.tenant_id if caller else "unresolved",
        )
        try: operations.access_audit.append(event)
        except Exception:
            operations.metrics.observe(ApiMetric(route, request.method, 503, duration, now, "AUDIT_FAILURE"))
            body = ApiError(code="AUDIT_UNAVAILABLE", message="internal access audit is unavailable",
                            correlation_id=correlation)
            response = JSONResponse(status_code=503, content=body.model_dump(mode="json"))
            response.headers["x-correlation-id"] = correlation
            response.headers["x-jmorais-intended-use"] = "internal-development-only"
        operations.structured_log.emit(ApiLogRecord(
            correlation_id=correlation, caller_id=caller.caller_id if caller else "UNAUTHENTICATED",
            route_template=route, purpose=caller.purpose.value if caller else "UNSPECIFIED",
            status=response.status_code, duration_ms=duration,
            policy_version=caller.policy_version if caller else "api-access-v1", occurred_at=now,
        ))
        if request.url.path in workspace_paths:
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        if request.url.path not in workspace_paths:
            return await request_validation_exception_handler(request, exc)
        body = ApiError(code="INVALID_REQUEST", message="invalid exact-reference request",
                        correlation_id=request.state.correlation_id)
        return JSONResponse(status_code=422, content=body.model_dump(mode="json"))

    @app.exception_handler(ApiBoundaryError)
    async def boundary_error(request: Request, exc: ApiBoundaryError):
        body = ApiError(code=exc.code, message=str(exc), correlation_id=request.state.correlation_id)
        return JSONResponse(status_code=exc.status_code, content=body.model_dump(mode="json"))

    @app.exception_handler(Exception)
    async def internal_error(request: Request, exc: Exception):
        body = ApiError(code="INTERNAL_ERROR", message="internal API request failed", correlation_id=request.state.correlation_id)
        return JSONResponse(status_code=500, content=body.model_dump(mode="json"))

    def require(resource_class: str):
        async def authorize(request: Request) -> CallerContext:
            authorization = request.headers.get("authorization", "")
            purpose = request.headers.get("x-purpose", "")
            if resource_class in {"WORKSPACE_READ", "CLINICAL_SUMMARY"}:
                # The operation fixes purpose; IAM must authorize it for the principal.
                if purpose and purpose != PurposeOfUse.CLINICAL_REVIEW.value:
                    raise ApiBoundaryError("AUTHORIZATION_DENIED", "workspace purpose rejected", 403)
                purpose = PurposeOfUse.CLINICAL_REVIEW.value
                if any(name in request.headers for name in
                       ("x-organization-id", "x-role", "x-roles", "x-authorization-state")):
                    raise ApiBoundaryError("AUTHORIZATION_DENIED", "caller context override prohibited", 403)
            if not authorization.startswith("Bearer "):
                raise ApiBoundaryError("AUTHENTICATION_REQUIRED", "authenticated internal caller is required", 401)
            if request.headers.get("x-tenant-id"):
                raise ApiBoundaryError("TENANT_SPOOFING_REJECTED", "caller-supplied tenant is prohibited", 401)
            try:
                caller = operations.authentication.authenticate(
                    CallerCredentials(authorization[7:].strip(), purpose), request.state.correlation_id)
            except (AuthenticationRejected, IdentityAuthenticationRejected) as exc:
                raise ApiBoundaryError("AUTHENTICATION_REJECTED", "caller authentication rejected", 401) from exc
            if not isinstance(caller, CallerContext):
                raise ApiBoundaryError("AUTHENTICATION_REJECTED", "caller context is malformed", 401)
            if caller.correlation_id != request.state.correlation_id or not caller.caller_id or not caller.policy_version:
                raise ApiBoundaryError("AUTHENTICATION_REJECTED", "caller context is malformed", 401)
            try: operations.authorization.authorize(caller, resource_class)
            except IdentityAuthorizationRejected as exc:
                raise ApiBoundaryError("AUTHORIZATION_DENIED", "caller is not authorized for endpoint", 403) from exc
            request.state.caller = caller
            if operations.tenant_context is None:
                yield caller
                return
            try:
                with operations.tenant_context.bind(caller):
                    yield caller
            except TenantError as exc:
                raise ApiBoundaryError("AUTHORIZATION_DENIED", "tenant context rejected", 403) from exc
        return authorize

    readiness_access = require("READINESS")
    version_access = require("VERSION")
    build_access = require("VERSION")
    reasoning_access = require("REASONING_INPUT")
    evidence_access = require("GOVERNED_EVIDENCE")
    guideline_access = require("GUIDELINE")
    orthopedic_access = require("ORTHOPEDIC")
    document_access = require("MEDICAL_DOCUMENT")
    defense_access = require("AUDIT_DEFENSE")

    summary_access = require("CLINICAL_SUMMARY")

    @app.post(f"{PREFIX}/workspace/summary/resolve", response_model=ClinicalSummaryResponse)
    def clinical_summary(body: ClinicalSummaryRequest,
                         _caller: CallerContext = Depends(summary_access)) -> ClinicalSummaryResponse:
        try:
            if operations.tenant_context is None:
                raise ApiBoundaryError("AUTHORIZATION_DENIED", "tenant context required", 403)
            tenant = current_tenant_context()
            if (tenant.tenant_id != _caller.tenant_id or
                    body.reference.tenant_id != tenant.tenant_id):
                raise ApiBoundaryError("AUTHORIZATION_DENIED", "tenant context rejected", 403)
            if workspace is None:
                raise ApiBoundaryError("WORKSPACE_UNAVAILABLE", "workspace unavailable", 503)
            view = workspace.clinical_summary(body.reference.to_reference())
            return ClinicalSummaryResponse(**asdict(view))
        except ApiBoundaryError:
            raise
        except TenantError as exc:
            raise ApiBoundaryError("AUTHORIZATION_DENIED", "tenant context rejected", 403) from exc
        except (ClinicalStateExactReferenceError, WorkspaceReadRejected) as exc:
            raise ApiBoundaryError("EXACT_REFERENCE_REJECTED", "exact reference rejected", 409) from exc
        except Exception as exc:
            raise ApiBoundaryError("INTERNAL_ERROR", "workspace request failed", 500) from exc

    workspace_access = require("WORKSPACE_READ")

    @app.post(f"{PREFIX}/workspace/bootstrap", response_model=WorkspaceBootstrapResponse)
    def workspace_bootstrap(body: WorkspaceBootstrapRequest, response: Response,
                            caller: CallerContext = Depends(workspace_access)):
        response.headers["Cache-Control"] = "no-store"
        if launch_service is None:
            raise ApiBoundaryError("WORKSPACE_UNAVAILABLE", "workspace unavailable", 503)
        try:
            launch = launch_service.get_exact(caller, body.reference)
            return WorkspaceBootstrapResponse(references=launch.references)
        except Exception:
            raise ApiBoundaryError("LAUNCH_UNAVAILABLE", "launch unavailable", 403) from None

    @app.get(f"{PREFIX}/workspace/context", response_model=WorkspaceContextResponse)
    def workspace_context(caller: CallerContext = Depends(workspace_access)):
        try:
            if operations.tenant_context is None:
                raise ApiBoundaryError("AUTHORIZATION_DENIED", "tenant context required", 403)
            tenant = current_tenant_context()
            if (tenant.tenant_id, tenant.organization_id, tenant.principal_id) != (
                    caller.tenant_id, caller.organization_id, caller.caller_id):
                raise ApiBoundaryError("AUTHORIZATION_DENIED", "tenant context rejected", 403)
            return WorkspaceContextResponse(caller_id=caller.caller_id, tenant_id=tenant.tenant_id,
                organization_id=tenant.organization_id, role=caller.role.value,
                purpose=caller.purpose.value, permissions=("WORKSPACE_READ",))
        except TenantError as exc:
            raise ApiBoundaryError("AUTHORIZATION_DENIED", "tenant context rejected", 403) from exc

    def resolve_workspace(body, caller, target, method, response_type):
        try:
            if operations.tenant_context is None:
                raise ApiBoundaryError("AUTHORIZATION_DENIED", "tenant context required", 403)
            tenant = current_tenant_context()
            if tenant.tenant_id != caller.tenant_id or body.reference.tenant_id != tenant.tenant_id:
                raise ApiBoundaryError("AUTHORIZATION_DENIED", "tenant context rejected", 403)
            if target is None:
                raise ApiBoundaryError("WORKSPACE_UNAVAILABLE", "workspace unavailable", 503)
            view = getattr(target, method)(body.reference.to_reference())
            return response_type(**asdict(view))
        except ApiBoundaryError:
            raise
        except TenantError as exc:
            raise ApiBoundaryError("AUTHORIZATION_DENIED", "tenant context rejected", 403) from exc
        except (ClinicalStateExactReferenceError, GovernedEvidenceExactReferenceError,
                ClinicalReasoningInputExactReferenceError, MedicalDocumentExactReferenceError,
                HumanReviewExactReferenceError, GovernedLLMDraftExactReferenceError,
                LLMInvocationExactReferenceError, AuditDefenseError, WorkspaceReadRejected) as exc:
            raise ApiBoundaryError("EXACT_REFERENCE_REJECTED", "exact reference rejected", 409) from exc
        except Exception as exc:
            raise ApiBoundaryError("INTERNAL_ERROR", "workspace request failed", 500) from exc

    @app.post(f"{PREFIX}/workspace/timeline/resolve", response_model=TimelineResponse)
    def workspace_timeline(body: TimelineRequest, caller: CallerContext = Depends(workspace_access)):
        return resolve_workspace(body, caller, remaining_workspace, "timeline", TimelineResponse)

    @app.post(f"{PREFIX}/workspace/evidence/resolve", response_model=EvidenceResponse)
    def workspace_evidence(body: EvidenceRequest, caller: CallerContext = Depends(workspace_access)):
        return resolve_workspace(body, caller, workspace, "evidence", EvidenceResponse)

    @app.post(f"{PREFIX}/workspace/explainability/resolve", response_model=ExplainabilityResponse)
    def workspace_explainability(body: ExplainabilityRequest, caller: CallerContext = Depends(workspace_access)):
        return resolve_workspace(body, caller, workspace, "explainability", ExplainabilityResponse)

    @app.post(f"{PREFIX}/workspace/medical-document/resolve", response_model=WorkspaceDocumentResponse)
    def workspace_medical_document(body: MedicalDocumentRequest, caller: CallerContext = Depends(workspace_access)):
        return resolve_workspace(body, caller, remaining_workspace, "medical_document", WorkspaceDocumentResponse)

    @app.post(f"{PREFIX}/workspace/human-review/resolve", response_model=HumanReviewResponse)
    def workspace_human_review(body: HumanReviewRequest, caller: CallerContext = Depends(workspace_access)):
        return resolve_workspace(body, caller, remaining_workspace, "human_review", HumanReviewResponse)

    @app.post(f"{PREFIX}/workspace/audit-defense/resolve", response_model=WorkspaceDefenseResponse)
    def workspace_audit_defense(body: AuditDefenseRequest, caller: CallerContext = Depends(workspace_access)):
        return resolve_workspace(body, caller, remaining_workspace, "audit_defense", WorkspaceDefenseResponse)

    @app.get(f"{PREFIX}/health/live", response_model=HealthResponse)
    def live() -> HealthResponse: return HealthResponse(status="LIVE")

    @app.get(f"{PREFIX}/health/ready", response_model=ReadinessResponse)
    def ready(response: Response, _caller: CallerContext = Depends(readiness_access)) -> ReadinessResponse:
        missing = services.missing()
        composition = ReadinessCheckResponse(name="application_composition", ready=not missing,
            code="COMPLETE" if not missing else "INCOMPLETE")
        report = operations.readiness.check()
        checks = (composition,) + tuple(ReadinessCheckResponse(name=x.name, ready=x.ready, code=x.code)
                                        for x in report.checks)
        ready_now = not missing and report.ready
        degraded = ready_now and any(item.code == "DEGRADED" for item in report.checks)
        if not ready_now: response.status_code = 503
        return ReadinessResponse(status="DEGRADED" if degraded else ("READY" if ready_now else "NOT_READY"), api_version=API_VERSION,
                                 missing_dependencies=missing, checks=checks)

    @app.get(f"{PREFIX}/version", response_model=VersionResponse)
    def version(_caller: CallerContext = Depends(version_access)) -> VersionResponse:
        return VersionResponse(api_version=API_VERSION, platform_version=PLATFORM_VERSION)

    @app.get(f"{PREFIX}/build", response_model=BuildResponse)
    def build(_caller: CallerContext = Depends(build_access)) -> BuildResponse:
        metadata = operations.build_metadata
        if metadata is None: raise ApiBoundaryError("BUILD_METADATA_UNAVAILABLE", "build metadata is unavailable", 503)
        return BuildResponse(**metadata)

    @app.get(f"{PREFIX}/clinical-reasoning-inputs/{{input_id}}", response_model=ClinicalReasoningInputResponse)
    def reasoning_input(input_id: str, _caller: CallerContext = Depends(reasoning_access)) -> ClinicalReasoningInputResponse:
        value = _required(services.reasoning_inputs.get(input_id), ClinicalReasoningInput, "ClinicalReasoningInput")
        if value.review_status is not ReasoningReviewStatus.APPROVED or value.readiness is not ReasoningReadiness.READY_FOR_REASONING:
            raise ApiBoundaryError("REVIEW_REQUIRED", "ClinicalReasoningInput is not approved and ready")
        return ClinicalReasoningInputResponse(input_id=value.input_id, subject_reference=value.subject_reference,
            input_version=value.input_version, previous_input_id=value.previous_input_id,
            clinical_state_reference_id=value.patient_clinical_state.reference_id,
            clinical_state_version=value.patient_clinical_state.clinical_state_version,
            patient_context_version=value.patient_clinical_state.patient_context_version,
            terminology_version=value.terminology_version, governed_evidence_ids=tuple(x.reference_id for x in value.evidence.all),
            applicable_guideline_ids=tuple(x.reference_id for x in value.applicable_guidelines),
            timeline_reference_id=value.timeline.reference_id, review_status=value.review_status.value,
            readiness=value.readiness.value, policy_versions=tuple(x.policy_version for x in value.policy_versions),
            provenance_reference_ids=tuple(x.reference_id for x in value.provenance_references), created_at=value.created_at)

    @app.get(f"{PREFIX}/governed-evidence/{{evidence_id}}", response_model=GovernedEvidenceResponse)
    def evidence(evidence_id: str, _caller: CallerContext = Depends(evidence_access)) -> GovernedEvidenceResponse:
        value = _required(services.governed_evidence.get(evidence_id), GovernedEvidence, "GovernedEvidence")
        lifecycle = services.evidence_lifecycle.current_status(value)
        if lifecycle != "ACTIVE": raise ApiBoundaryError("INELIGIBLE_EVIDENCE", f"GovernedEvidence lifecycle is {lifecycle}")
        return GovernedEvidenceResponse(governed_evidence_id=value.governed_evidence_id,
            evidence_level=value.evidence_level, methodological_quality=value.methodological_quality,
            recommendation_strength=value.recommendation_strength, applicability=value.applicability,
            lifecycle_status=lifecycle, support_directions=value.support_directions,
            provenance_references=value.provenance_references, ledger_references=value.ledger_references,
            policy_version=value.policy_version, appraisal_version=value.appraisal_version,
            limitations=value.limitations, issued_at=value.issued_at)

    @app.get(f"{PREFIX}/guideline-recommendation-sets", response_model=GuidelineRecommendationSetResponse)
    def guidelines(subject_reference: str, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100),
                   _caller: CallerContext = Depends(guideline_access)):
        value = _required(services.guideline_recommendations.latest(subject_reference), GuidelineRecommendationSet, "GuidelineRecommendationSet")
        _approved(value.review_status, "GuidelineRecommendationSet")
        selected, page = _page(value.recommendations, offset, limit)
        refs = tuple(RecommendationReference(recommendation_id=x.recommendation_id, guideline_id=x.guideline_id,
            guideline_version=x.guideline_version, intent=x.intent.value, readiness=x.readiness.value,
            review_status=x.review_status.value, governed_evidence_ids=x.governed_evidence_ids,
            provenance_references=x.provenance_references) for x in selected)
        return GuidelineRecommendationSetResponse(set_id=value.set_id, subject_reference=value.subject_reference,
            set_version=value.set_version, reasoning_input_id=value.reasoning_input_id, readiness=value.readiness.value,
            review_status=value.review_status.value, policy_version=value.policy_version, recommendations=refs,
            page=page, provenance_references=value.provenance_references, generated_at=value.generated_at)

    @app.get(f"{PREFIX}/orthopedic-assessment-sets", response_model=OrthopedicAssessmentSetResponse)
    def orthopedic(subject_reference: str, _caller: CallerContext = Depends(orthopedic_access)):
        value = _required(services.orthopedic_assessments.latest(subject_reference), OrthopedicAssessmentSet, "OrthopedicAssessmentSet")
        _approved(value.review_status, "OrthopedicAssessmentSet"); item = value.assessment
        return OrthopedicAssessmentSetResponse(set_id=value.set_id, subject_reference=value.subject_reference,
            set_version=value.set_version, reasoning_input_id=item.reasoning_input_id, assessment_id=item.assessment_id,
            readiness=item.readiness.value, review_status=item.review_status.value, terminology_version=item.terminology_version,
            governed_evidence_ids=item.governed_evidence_ids, guideline_recommendation_ids=item.guideline_recommendation_ids,
            quality_flags=item.quality_flags, limitations=item.limitations, policy_version=item.policy_version,
            provenance_references=item.provenance_references, generated_at=value.generated_at)

    @app.get(f"{PREFIX}/medical-documents/{{stream_id}}", response_model=MedicalDocumentResponse)
    def document(stream_id: str, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100),
                 _caller: CallerContext = Depends(document_access)):
        value = _required(services.medical_documents.latest(stream_id), MedicalDocumentVersion, "MedicalDocument")
        item = value.document; _approved(item.review_status, "MedicalDocument")
        if item.status is not DocumentStatus.APPROVED_BY_REVIEWER or not item.validation.valid:
            raise ApiBoundaryError("DOCUMENT_BLOCKED", "MedicalDocument did not pass governed validation")
        selected, page = _page(item.sections, offset, limit)
        sections = tuple(DocumentSectionReference(section_id=x.section_id, title=x.title, order=x.order,
            provenance_references=x.provenance_references) for x in selected)
        return MedicalDocumentResponse(version_id=value.version_id, document_stream_id=value.document_stream_id,
            version=value.version, document_id=item.document_id, document_type=item.document_type.value,
            reasoning_input_id=item.reasoning_input_id, reasoning_input_version=item.reasoning_input_version,
            clinical_state_reference_id=item.clinical_state_reference_id, clinical_state_version=item.clinical_state_version,
            status=item.status.value, review_status=item.review_status.value, validation_gate_version=item.validation.gate_version,
            sections=sections, page=page, policy_versions=item.policy_versions,
            provenance_references=item.provenance_references, created_at=value.created_at)

    @app.get(f"{PREFIX}/audit-defenses/{{stream_id}}", response_model=AuditDefenseResponse)
    def audit_defense(stream_id: str, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100),
                      _caller: CallerContext = Depends(defense_access)):
        value = _required(services.audit_defenses.latest(stream_id), DefensePackage, "AuditDefense")
        item = value.defense; _approved(item.review_status, "AuditDefense")
        if item.status is not DefenseStatus.APPROVED_BY_REVIEWER:
            raise ApiBoundaryError("DEFENSE_BLOCKED", "AuditDefense is not approved")
        selected, page = _page(item.arguments, offset, limit)
        arguments = tuple(DefenseArgumentReference(argument_id=x.argument_id, argument_code=x.argument_code,
            position=x.position.value, provenance_references=x.provenance_references) for x in selected)
        return AuditDefenseResponse(package_id=value.package_id, stream_id=value.stream_id, version=value.version,
            defense_id=item.defense_id, reasoning_input_id=item.reasoning_input_id,
            reasoning_input_version=item.reasoning_input_version, orthopedic_assessment_set_id=item.orthopedic_assessment_set_id,
            status=item.status.value, review_status=item.review_status.value, arguments=arguments, page=page,
            provenance_references=item.provenance_references, created_at=value.created_at)

    if runtime_security is not None:
        from .runtime_security import RuntimeSecurityMiddleware
        app.add_middleware(RuntimeSecurityMiddleware, policy=runtime_security)
    return app
