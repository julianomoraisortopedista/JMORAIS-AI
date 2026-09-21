from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi.testclient import TestClient

from jmoraIs.api import ApiOperationalServices, ApiServices, create_app
from jmoraIs.api.security import CallerRole, PurposeOfUse, ReadinessCheck
from jmoraIs.api.security_infrastructure import (
    DeterministicDevelopmentAuthenticator, DevelopmentIdentity, InMemoryApiAccessAudit,
    InMemoryApiMetrics, InMemoryStructuredLog, StaticReadinessProbe,
)
from jmoraIs.api.identity_security import CanonicalApiAuthorizationPolicy
from jmoraIs.appraisal.governed import GovernedEvidence
from jmoraIs.audit_defense.domain import DefensePackage, DefenseStatus
from jmoraIs.clinical.governed import HumanReviewStatus
from jmoraIs.guideline_engine.domain import GuidelineRecommendationSet, RecommendationIntent, RecommendationReadiness
from jmoraIs.medical_documents.domain import DocumentStatus, DocumentType, MedicalDocumentVersion
from jmoraIs.orthopedic_intelligence.domain import AssessmentReadiness, OrthopedicAssessmentSet
from jmoraIs.reasoning_input.domain import ClinicalReasoningInput, ReasoningReadiness, ReasoningReviewStatus

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
APPROVED = HumanReviewStatus.APPROVED_BY_REVIEWER
TOKENS = {"service": "service-token-for-tests-0000001", "reviewer": "reviewer-token-for-tests-000001",
          "admin": "administrator-token-for-tests-01"}


class Query:
    def __init__(self, value): self.value = value
    def get(self, _identifier): return self.value
    def latest(self, _identifier): return self.value


class Lifecycle:
    def __init__(self, status="ACTIVE"): self.status = status
    def current_status(self, _value): return self.status


def entity(cls, **attributes):
    value = object.__new__(cls)
    for name, item in attributes.items(): object.__setattr__(value, name, item)
    return value


def ref(identifier, **extra):
    return SimpleNamespace(reference_id=identifier, policy_version="policy-v1", **extra)


def services(*, reasoning_status=ReasoningReviewStatus.APPROVED, lifecycle="ACTIVE", approved=True):
    review = APPROVED if approved else HumanReviewStatus.PENDING_REVIEW
    reasoning = entity(ClinicalReasoningInput, input_id="ri-1", subject_reference="pt-1", input_version=2,
        previous_input_id="ri-0", patient_clinical_state=ref("state-1", clinical_state_version=3, patient_context_version=4),
        terminology_version="term-v1", evidence=SimpleNamespace(all=(ref("ge-1"),)),
        applicable_guidelines=(ref("guideline-1"),), timeline=ref("timeline-1"), review_status=reasoning_status,
        readiness=ReasoningReadiness.READY_FOR_REASONING, policy_versions=(ref("pv-1"),),
        provenance_references=(ref("prov-1"),), created_at=NOW)
    evidence = entity(GovernedEvidence, governed_evidence_id="ge-1", evidence_level="RCT",
        methodological_quality="HIGH", recommendation_strength="STRONG_FOR", applicability=("ADULT",),
        support_directions=("SUPPORTING",), provenance_references=("prov-1",), ledger_references=("ledger-1",),
        policy_version="policy-v1", appraisal_version="app-v1", limitations=(), issued_at=NOW)
    recommendation = SimpleNamespace(recommendation_id="rec-1", guideline_id="guide-1", guideline_version="1",
        intent=RecommendationIntent.CONSIDER, readiness=RecommendationReadiness.READY_FOR_HUMAN_REVIEW,
        review_status=review, governed_evidence_ids=("ge-1",), provenance_references=("prov-1",))
    guidelines = entity(GuidelineRecommendationSet, set_id="gs-1", subject_reference="pt-1", set_version=2,
        reasoning_input_id="ri-1", readiness=RecommendationReadiness.READY_FOR_HUMAN_REVIEW,
        review_status=review, policy_version="policy-v1", recommendations=(recommendation, recommendation),
        provenance_references=("prov-1",), generated_at=NOW)
    assessment = SimpleNamespace(assessment_id="oa-1", reasoning_input_id="ri-1",
        readiness=AssessmentReadiness.READY_FOR_HUMAN_REVIEW, review_status=review, terminology_version="term-v1",
        governed_evidence_ids=("ge-1",), guideline_recommendation_ids=("rec-1",), quality_flags=(), limitations=(),
        policy_version="policy-v1", provenance_references=("prov-1",))
    orthopedic = entity(OrthopedicAssessmentSet, set_id="os-1", subject_reference="pt-1", set_version=1,
        assessment=assessment, review_status=review, generated_at=NOW)
    section = SimpleNamespace(section_id="s1", title="Governed summary", order=1, provenance_references=("prov-1",))
    document = SimpleNamespace(document_id="doc-1", document_type=DocumentType.MEDICAL_SUMMARY,
        reasoning_input_id="ri-1", reasoning_input_version=2, clinical_state_reference_id="state-1",
        clinical_state_version=3, status=DocumentStatus.APPROVED_BY_REVIEWER, review_status=review,
        validation=SimpleNamespace(valid=True, gate_version="gate-v1"), sections=(section, section),
        policy_versions=("policy-v1",), provenance_references=("prov-1",))
    document_version = entity(MedicalDocumentVersion, version_id="dv-1", document_stream_id="ds-1",
        version=1, document=document, created_at=NOW)
    argument = SimpleNamespace(argument_id="a1", argument_code="SUPPORTED", position=SimpleNamespace(value="SUPPORTED"),
        provenance_references=("prov-1",))
    defense = SimpleNamespace(defense_id="def-1", reasoning_input_id="ri-1", reasoning_input_version=2,
        orthopedic_assessment_set_id="os-1", status=DefenseStatus.APPROVED_BY_REVIEWER, review_status=review,
        arguments=(argument, argument), provenance_references=("prov-1",))
    defense_package = entity(DefensePackage, package_id="dp-1", stream_id="audit-1", version=1,
        defense=defense, created_at=NOW)
    return ApiServices(Query(reasoning), Query(evidence), Lifecycle(lifecycle), Query(guidelines),
        Query(orthopedic), Query(document_version), Query(defense_package))


def operational(*, ready=True):
    identities = (
        DevelopmentIdentity.from_token("svc-1", CallerRole.INTERNAL_SERVICE, TOKENS["service"],
            (PurposeOfUse.INTERNAL_OPERATIONS,), "api-access-v1"),
        DevelopmentIdentity.from_token("reviewer-1", CallerRole.CLINICAL_REVIEWER, TOKENS["reviewer"],
            (PurposeOfUse.CLINICAL_REVIEW,), "api-access-v1"),
        DevelopmentIdentity.from_token("admin-1", CallerRole.ADMINISTRATOR, TOKENS["admin"],
            (PurposeOfUse.ADMINISTRATION,), "api-access-v1"),
    )
    checks = (ReadinessCheck("postgresql", ready, "AVAILABLE" if ready else "UNAVAILABLE"),
              ReadinessCheck("migrations", ready, "CURRENT" if ready else "UNKNOWN"),
              ReadinessCheck("critical_dependencies", ready, "AVAILABLE" if ready else "UNAVAILABLE"))
    audit, metrics = InMemoryApiAccessAudit(), InMemoryApiMetrics()
    return ApiOperationalServices(DeterministicDevelopmentAuthenticator(identities),
        CanonicalApiAuthorizationPolicy(), StaticReadinessProbe(checks), audit, metrics, InMemoryStructuredLog())


def headers(identity="service"):
    purposes = {"service": "INTERNAL_OPERATIONS", "reviewer": "CLINICAL_REVIEW", "admin": "ADMINISTRATION"}
    return {"authorization": f"Bearer {TOKENS[identity]}", "x-purpose": purposes[identity]}


def client(api_services=None, *, identity="service", ready=True):
    ops = operational(ready=ready)
    return TestClient(create_app(api_services or services(), ops), headers=headers(identity)), ops


def test_operational_endpoints_and_internal_use_headers():
    api, _ = client()
    live = api.get("/internal/api/v1/health/live", headers={"x-correlation-id": "case-123"})
    assert live.status_code == 200 and live.json() == {"status": "LIVE"}
    assert live.headers["x-correlation-id"] == "case-123"
    assert live.headers["x-jmorais-intended-use"] == "internal-development-only"
    assert api.get("/internal/api/v1/health/ready").json()["status"] == "READY"
    assert api.get("/internal/api/v1/version").json()["intended_use"] == "INTERNAL_DEVELOPMENT_ONLY"


def test_readiness_fails_closed_with_standardized_error():
    api, _ = client(ApiServices(), ready=False)
    response = api.get("/internal/api/v1/health/ready", headers={**headers(), "x-correlation-id": "invalid correlation id"})
    assert response.status_code == 503
    assert response.json()["status"] == "NOT_READY"
    assert {item["name"] for item in response.json()["checks"]} == {
        "application_composition", "postgresql", "migrations", "critical_dependencies"}
    assert response.headers["x-correlation-id"] != "invalid correlation id"


def test_all_read_only_resources_return_versioned_reference_dtos_with_pagination():
    api, _ = client()
    reasoning = api.get("/internal/api/v1/clinical-reasoning-inputs/ri-1").json()
    assert reasoning["contract_version"] == "v1" and reasoning["governed_evidence_ids"] == ["ge-1"]
    assert "evidence_packages" not in reasoning and "patient_context" not in reasoning
    evidence = api.get("/internal/api/v1/governed-evidence/ge-1").json()
    assert evidence["lifecycle_status"] == "ACTIVE" and "evidence_package_id" not in evidence
    guidelines = api.get("/internal/api/v1/guideline-recommendation-sets?subject_reference=pt-1&offset=1&limit=1").json()
    assert guidelines["page"] == {"offset": 1, "limit": 1, "returned": 1, "total": 2}
    reviewer, _ = client(identity="reviewer")
    assert reviewer.get("/internal/api/v1/orthopedic-assessment-sets?subject_reference=pt-1").status_code == 200
    document = reviewer.get("/internal/api/v1/medical-documents/ds-1?limit=1").json()
    assert document["page"]["total"] == 2 and len(document["sections"]) == 1
    defense = reviewer.get("/internal/api/v1/audit-defenses/audit-1?limit=1").json()
    assert defense["page"]["total"] == 2 and len(defense["arguments"]) == 1


def test_api_rejects_unreviewed_revoked_and_forged_artifacts():
    unreviewed, _ = client(services(reasoning_status=ReasoningReviewStatus.REVIEWED))
    assert unreviewed.get("/internal/api/v1/clinical-reasoning-inputs/ri-1").json()["code"] == "REVIEW_REQUIRED"
    revoked, _ = client(services(lifecycle="RETRACTED"))
    assert revoked.get("/internal/api/v1/governed-evidence/ge-1").json()["code"] == "INELIGIBLE_EVIDENCE"
    pending, _ = client(services(approved=False))
    assert pending.get("/internal/api/v1/guideline-recommendation-sets?subject_reference=pt-1").json()["code"] == "REVIEW_REQUIRED"
    forged = services(); forged = ApiServices(Query({"input_id": "ri-1"}), forged.governed_evidence,
        forged.evidence_lifecycle, forged.guideline_recommendations, forged.orthopedic_assessments,
        forged.medical_documents, forged.audit_defenses)
    response = client(forged)[0].get("/internal/api/v1/clinical-reasoning-inputs/ri-1")
    assert response.status_code == 409 and response.json()["code"] == "TRUST_BOUNDARY_REJECTED"


def test_authentication_purpose_roles_audit_metrics_and_safe_errors():
    ops = operational(); app = TestClient(create_app(services(), ops), raise_server_exceptions=False)
    anonymous = app.get("/internal/api/v1/version")
    assert anonymous.status_code == 401 and anonymous.json()["code"] == "AUTHENTICATION_REQUIRED"
    invalid = app.get("/internal/api/v1/version", headers={"authorization": "Bearer invalid-token-value-00000000",
        "x-purpose": "INTERNAL_OPERATIONS"})
    assert invalid.status_code == 401 and invalid.json()["code"] == "AUTHENTICATION_REJECTED"
    missing = app.get("/internal/api/v1/version", headers={"authorization": f"Bearer {TOKENS['service']}"})
    assert missing.status_code == 401 and "traceback" not in missing.text.lower()
    unauthorized = app.get("/internal/api/v1/orthopedic-assessment-sets?subject_reference=pt-1", headers=headers())
    assert unauthorized.status_code == 403 and unauthorized.json()["code"] == "AUTHORIZATION_DENIED"
    assert app.get("/internal/api/v1/version", headers=headers("service")).status_code == 200
    assert app.get("/internal/api/v1/medical-documents/ds-1", headers=headers("reviewer")).status_code == 200
    assert app.get("/internal/api/v1/audit-defenses/audit-1", headers=headers("admin")).status_code == 200
    assert ops.access_audit.events and ops.metrics.metrics
    event = ops.access_audit.events[-1]
    assert set(event.__dict__) == {"event_id", "caller_id", "role", "purpose", "correlation_id",
        "policy_version", "route_template", "method", "outcome", "status_code", "duration_ms", "occurred_at",
        "tenant_id"}
    assert "pt-1" not in repr(event) and "clinical" not in repr(event).lower()


def test_request_size_is_bounded_without_leaking_content():
    api, _ = client()
    response = api.get("/internal/api/v1/version", headers={**headers(), "content-length": "1048577"})
    assert response.status_code == 413 and response.json()["code"] == "REQUEST_TOO_LARGE"


def test_malformed_authenticated_context_is_rejected():
    class MalformedAuthenticator:
        def authenticate(self, credentials, correlation_id): return {"caller_id": "forged"}
    ops = operational()
    malformed = ApiOperationalServices(MalformedAuthenticator(), ops.authorization, ops.readiness, ops.access_audit,
        ops.metrics, ops.structured_log)
    response = TestClient(create_app(services(), malformed)).get("/internal/api/v1/version", headers=headers())
    assert response.status_code == 401 and response.json()["code"] == "AUTHENTICATION_REJECTED"


def test_default_asgi_composition_is_fail_closed(monkeypatch):
    import importlib
    from jmoraIs.api import asgi
    monkeypatch.delenv("JMORAIS_DEV_INTERNAL_TOKEN", raising=False)
    module = importlib.reload(asgi)
    api = TestClient(module.app)
    assert api.get("/internal/api/v1/health/live").status_code == 200
    assert api.get("/internal/api/v1/version").status_code == 401
