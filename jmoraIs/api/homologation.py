from __future__ import annotations
from .workspace_launch import ClinicalWorkspaceLaunchService
from jmoraIs.infrastructure.workspace_launch import PostgreSQLClinicalWorkspaceLaunchRepository

from dataclasses import dataclass

from jmoraIs.application.evidence_packages import ScientificEvidencePackagePort
from jmoraIs.appraisal.governed import GovernedEvidenceService
from jmoraIs.appraisal.persistence import SQLAlchemyGovernedEvidenceRepository
from jmoraIs.audit_defense.persistence import PostgreSQLAuditDefenseRepository
from jmoraIs.clinical.governance_persistence import (
    PostgreSQLReviewerIdentityRepository, SQLAlchemyGovernedDecisionAuditRepository,
    SQLAlchemyGovernedEvidenceLifecycleRepository,
)
from jmoraIs.clinical.review_governance import (
    AuthorizedRecommendationReviewService, GovernedEvidenceReevaluationService, ReviewAuthorizationPolicy,
)
from jmoraIs.guideline_engine.persistence import PostgreSQLRecommendationRepository
from jmoraIs.infrastructure.api_operational_audit import PostgreSQLApiAccessAuditAdapter
from jmoraIs.infrastructure.api_readiness import PostgreSQLApiReadinessAdapter
from jmoraIs.infrastructure.identity_persistence import (
    PostgreSQLExternalIdentityLinkRepository, PostgreSQLIdentitySecurityAudit,
)
from jmoraIs.infrastructure.oidc_identity import OIDCIdentityProviderAdapter, OIDCSigningKeyProvider
from jmoraIs.infrastructure.secret_backed_database import SecretBackedDatabaseEngine
from jmoraIs.infrastructure.managed_secrets import ManagedHmacPseudonymizationKeyAdapter
from jmoraIs.infrastructure.secret_persistence import PostgreSQLKeyMetadataRepository, PostgreSQLSecretSecurityAudit
from jmoraIs.infrastructure.tenant_persistence import (
    CANONICAL_TENANT_TABLES, PostgreSQLRLSReadiness, PostgreSQLTenantRepository,
    PostgreSQLTenantSecurityAudit,
)
from jmoraIs.infrastructure.session_persistence import (
    PostgreSQLReplayProtectionRepository, PostgreSQLSessionRepository, PostgreSQLSessionSecurityAudit,
)
from jmoraIs.identity.session_application import CanonicalSessionSecurityService
from jmoraIs.infrastructure.postgresql_package_catalog import PostgreSQLPackageCatalogRepository
from jmoraIs.medical_documents.persistence import PostgreSQLMedicalDocumentRepository
from jmoraIs.orthopedic_intelligence.persistence import PostgreSQLOrthopedicAssessmentRepository
from jmoraIs.reasoning_input.application import ClinicalReasoningInputQueryService
from jmoraIs.reasoning_input.persistence import PostgreSQLClinicalReasoningInputRepository
from jmoraIs.identity.reviewer import AuthenticatedReviewerResolver
from jmoraIs.tenancy.application import CanonicalTenantAuthorizationService, TrustedTenantResolutionService
from jmoraIs.tenancy.context import TenantContextBinder
from jmoraIs.secrets.domain import SecretReference

from jmoraIs.clinical_workspace import ClinicalWorkspace, RemainingClinicalWorkspace
from jmoraIs.clinical_state.exact_reference_persistence import PostgreSQLClinicalStateExactReferenceRepository
from jmoraIs.appraisal.exact_reference_persistence import PostgreSQLGovernedEvidenceExactReferenceRepository
from jmoraIs.infrastructure.appraisal_persistence import PostgreSQLClinicalAppraisalRepository
from jmoraIs.reasoning_input.exact_reference_persistence import PostgreSQLClinicalReasoningInputExactReferenceRepository
from jmoraIs.terminology import PostgreSQLTerminologyMappingGovernanceRepository
from jmoraIs.medical_documents.exact_reference_persistence import PostgreSQLMedicalDocumentExactReferenceRepository
from jmoraIs.llm_human_review.exact_reference_persistence import PostgreSQLHumanReviewExactReferenceRepository

from jmoraIs.infrastructure.managed_attestation import ManagedAttestationFactory, ManagedGovernedDraftVerifier
from jmoraIs.governed_llm_draft.exact_reference_persistence import PostgreSQLGovernedLLMDraftExactReferenceRepository
from jmoraIs.llm_gateway.exact_reference_persistence import PostgreSQLLLMInvocationExactReferenceRepository

from .app import ApiOperationalServices, ApiServices, create_app
from .configuration import InternalApiConfig, InternalApiEnvironment
from .security import ReadinessCheck, ReadinessReport
from .identity_security import CanonicalApiAuthorizationPolicy, ExternalIdentityApiAuthenticator
from .security_ports import ApiMetricsPort, ApiStructuredLogPort


class HomologationStartupError(RuntimeError): pass


class HomologationReadiness:
    def __init__(self, database, audit, mandatory: tuple[ReadinessCheck, ...]):
        self._database, self._audit, self._mandatory = database, audit, mandatory
    def check(self) -> ReadinessReport:
        report = self._database.check()
        return ReadinessReport(report.checks + (self._audit.readiness(),) + self._mandatory)


def startup_self_check(report: ReadinessReport) -> None:
    required = {"postgresql", "migrations", "repository_composition", "audit_backend",
        "metrics_backend", "authentication_backend", "identity_provider", "identity_signing_keys",
        "identity_repository", "reviewer_identity_repository", "authorization_policy", "critical_governance"}
    required.update({"tenant_repository", "tenant_rls", "tenant_aware_repositories",
                     "secrets_provider", "pseudonymization_key", "secret_backed_database"})
    required.update({"session_repository", "replay_repository", "session_security", "session_policy"})
    present = {item.name for item in report.checks}
    if not report.ready or not required.issubset(present):
        raise HomologationStartupError("mandatory homologation dependencies are not ready")


@dataclass(frozen=True)
class HomologationComposition:
    app: object
    api_services: ApiServices
    operational_services: ApiOperationalServices
    reviewer_authorization: PostgreSQLReviewerIdentityRepository
    reviewer_governance: AuthorizedRecommendationReviewService
    authenticated_reviewer: AuthenticatedReviewerResolver
    database_credentials: SecretBackedDatabaseEngine
    pseudonymization_keys: ManagedHmacPseudonymizationKeyAdapter
    workspace: ClinicalWorkspace
    remaining_workspace: RemainingClinicalWorkspace
    draft_attestor: object
    draft_references: PostgreSQLGovernedLLMDraftExactReferenceRepository
    launch_service: ClinicalWorkspaceLaunchService
    launch_producer: ClinicalWorkspaceLaunchService


def compose_homologation(config: InternalApiConfig, *, metrics: ApiMetricsPort,
                          structured_log: ApiStructuredLogPort, identity_http_get, secrets_provider) -> HomologationComposition:
    if (config.environment is not InternalApiEnvironment.HOMOLOGATION or config.oidc is None
            or config.database_credential is None or config.pseudonymization_key is None):
        raise HomologationStartupError("explicit homologation configuration is required")
    if not getattr(secrets_provider,"homologation_safe",False):
        raise HomologationStartupError("development secret providers are prohibited in homologation")
    database_credentials=SecretBackedDatabaseEngine(secrets_provider,config.database_credential,
        runtime_role=config.runtime_database_role, engine_options={
            "pool_size": config.runtime_security.database_pool_size,
            "max_overflow": config.runtime_security.database_max_overflow,
            "connect_timeout": config.runtime_security.database_connect_timeout_seconds,
            "statement_timeout_ms": config.runtime_security.database_statement_timeout_ms,
            "lock_timeout_ms": config.runtime_security.database_lock_timeout_ms,
            "idle_transaction_timeout_ms": config.runtime_security.database_idle_transaction_timeout_ms,
            "require_tls": config.runtime_security.database_tls_required,
        })
    engine=database_credentials.engine
    secret_audit=PostgreSQLSecretSecurityAudit(engine)
    key_metadata=PostgreSQLKeyMetadataRepository(engine)
    factory = ManagedAttestationFactory(secrets_provider, key_metadata)
    try:
        draft_attestor = factory.draft_attestor(config.governed_draft_signing_key,
                                               actor_id="governed-draft-runtime")
    except Exception as exc:
        database_credentials.close()
        raise HomologationStartupError("governed draft signing key unavailable") from None
    reader = engine.execution_options(postgresql_readonly=True)
    draft_references = PostgreSQLGovernedLLMDraftExactReferenceRepository(reader,
        ManagedGovernedDraftVerifier(factory, config.governed_draft_signing_key,
                                    actor_id="governed-draft-verifier"),
        invocation_references=PostgreSQLLLMInvocationExactReferenceRepository(reader))
    exact_states = PostgreSQLClinicalStateExactReferenceRepository(reader)
    exact_evidence = PostgreSQLGovernedEvidenceExactReferenceRepository(reader,
        ScientificEvidencePackagePort(catalog=PostgreSQLPackageCatalogRepository(reader)),
        PostgreSQLClinicalAppraisalRepository(reader),
        SQLAlchemyGovernedEvidenceLifecycleRepository(reader))
    exact_reasoning = PostgreSQLClinicalReasoningInputExactReferenceRepository(reader,
        exact_states, exact_evidence, PostgreSQLTerminologyMappingGovernanceRepository(reader))
    workspace = ClinicalWorkspace(exact_states, exact_evidence, exact_reasoning)
    remaining_workspace = RemainingClinicalWorkspace(exact_states,
        PostgreSQLMedicalDocumentExactReferenceRepository(reader),
        PostgreSQLHumanReviewExactReferenceRepository(reader, draft_references),
        PostgreSQLAuditDefenseRepository(reader))
    pseudonymization_keys=ManagedHmacPseudonymizationKeyAdapter(
        secrets_provider,key_metadata,secret_audit,metrics=metrics)
    tenant_repository = PostgreSQLTenantRepository(engine)
    tenant_audit = PostgreSQLTenantSecurityAudit(engine)
    tenant_resolution = TrustedTenantResolutionService(tenant_repository, tenant_audit)
    tenant_authorization = CanonicalTenantAuthorizationService(tenant_audit)
    tenant_binding = TenantContextBinder(tenant_audit)
    packages = ScientificEvidencePackagePort(catalog=PostgreSQLPackageCatalogRepository(engine))
    governed_repository = SQLAlchemyGovernedEvidenceRepository(engine)
    governed = GovernedEvidenceService(packages, governed_repository)
    lifecycle_repository = SQLAlchemyGovernedEvidenceLifecycleRepository(engine)
    lifecycle = GovernedEvidenceReevaluationService(packages, lifecycle_repository)
    reasoning = ClinicalReasoningInputQueryService(PostgreSQLClinicalReasoningInputRepository(engine))
    recommendations = PostgreSQLRecommendationRepository(engine)
    orthopedic = PostgreSQLOrthopedicAssessmentRepository(engine)
    documents = PostgreSQLMedicalDocumentRepository(engine)
    defenses = PostgreSQLAuditDefenseRepository(engine)
    reviewer_authorization = PostgreSQLReviewerIdentityRepository(engine)
    reviewer_audit = SQLAlchemyGovernedDecisionAuditRepository(engine)
    reviewer_governance = AuthorizedRecommendationReviewService(
        reviewer_authorization, reviewer_audit, ReviewAuthorizationPolicy())
    identity_links = PostgreSQLExternalIdentityLinkRepository(engine)
    identity_audit = PostgreSQLIdentitySecurityAudit(engine)
    session_repository = PostgreSQLSessionRepository(engine)
    replay_repository = PostgreSQLReplayProtectionRepository(engine)
    session_audit = PostgreSQLSessionSecurityAudit(engine)
    session_security = CanonicalSessionSecurityService(session_repository, replay_repository,
        session_audit, config.session_security, metrics=metrics)
    signing_keys = OIDCSigningKeyProvider(config.oidc, http_get=identity_http_get, metrics=metrics)
    identity_provider = OIDCIdentityProviderAdapter(config.oidc, signing_keys, identity_links,
        identity_audit, metrics=metrics, tenant_resolution=tenant_resolution, tenant_binding=tenant_binding,
        session_validation=session_security)
    authentication = ExternalIdentityApiAuthenticator(identity_provider, tenant_resolution, tenant_authorization)
    authorization = CanonicalApiAuthorizationPolicy(identity_audit)
    authenticated_reviewer = AuthenticatedReviewerResolver(identity_links, reviewer_authorization)
    api_services = ApiServices(reasoning, governed, lifecycle, recommendations, orthopedic, documents, defenses)
    audit = PostgreSQLApiAccessAuditAdapter(engine)
    identity_check = authentication.readiness()
    key_check = signing_keys.readiness()
    repository_check = identity_links.readiness()
    authentication_check = ReadinessCheck("authentication_backend", identity_check.ready,
        "AVAILABLE" if identity_check.ready else "UNAVAILABLE")
    metrics_check = metrics.readiness() if hasattr(metrics, "readiness") else \
        ReadinessCheck("metrics_backend", False, "UNVERIFIABLE")
    mandatory = (
        ReadinessCheck("repository_composition", True, "COMPLETE"),
        metrics_check,
        authentication_check,
        identity_check,
        key_check,
        repository_check,
        reviewer_authorization.readiness(),
        authorization.readiness(),
        tenant_repository.readiness(),
        PostgreSQLRLSReadiness(engine, CANONICAL_TENANT_TABLES).readiness(),
        ReadinessCheck("tenant_aware_repositories", True, "COMPOSED"),
        secrets_provider.readiness((config.database_credential,
            SecretReference(config.pseudonymization_key.provider,config.pseudonymization_key.key_id,
                            config.pseudonymization_key.purpose,config.pseudonymization_key.version),
            *config.provider_secret_references)),
        pseudonymization_keys.readiness(config.pseudonymization_key),
        ReadinessCheck("secret_backed_database", True, "AVAILABLE"),
        session_repository.readiness(), replay_repository.readiness(), session_security.readiness(),
        ReadinessCheck("session_policy", True, "ENFORCED"),
        ReadinessCheck("critical_governance", reviewer_governance is not None and lifecycle is not None,
                       "AVAILABLE" if reviewer_governance and lifecycle else "UNAVAILABLE"),
    )
    readiness = HomologationReadiness(PostgreSQLApiReadinessAdapter(engine), audit, mandatory)
    operations = ApiOperationalServices(authentication, authorization, readiness, audit, metrics,
                                         structured_log, tenant_binding)
    startup_self_check(readiness.check())
    launch_service = ClinicalWorkspaceLaunchService(PostgreSQLClinicalWorkspaceLaunchRepository(reader),
        authorization, workspace, remaining_workspace)
    launch_producer = ClinicalWorkspaceLaunchService(PostgreSQLClinicalWorkspaceLaunchRepository(engine),
        authorization, workspace, remaining_workspace)
    return HomologationComposition(create_app(api_services, operations, workspace=workspace,
        remaining_workspace=remaining_workspace, launch_service=launch_service), api_services, operations,
        reviewer_authorization, reviewer_governance, authenticated_reviewer,database_credentials,pseudonymization_keys,
        workspace,remaining_workspace,draft_attestor,draft_references,launch_service,launch_producer)
