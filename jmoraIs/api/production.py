from __future__ import annotations
from dataclasses import replace
from contextlib import asynccontextmanager
import platform

from jmoraIs.infrastructure.production_runtime import (
    CURRENT_SCHEMA_REVISION, PostgreSQLDeploymentAudit, ProductionIntegrityVerifier, deployment_event,
)
from jmoraIs.infrastructure.offline_replay import (
    OfflineReplayMode, OfflineReplayRequest, OfflineReplayVerifier, PostgreSQLOfflineReplayAudit,
    OfflineReplayVerificationError,
)
from .app import create_app
from .configuration import InternalApiConfig, InternalApiEnvironment
from .homologation import HomologationStartupError, compose_homologation

class ProductionStartupError(RuntimeError): pass

class ProductionComposition:
    def __init__(self, app, canonical, integrity_checks, deployment_audit, metrics, structured_log):
        self.app, self.canonical, self.integrity_checks = app, canonical, integrity_checks
        self.deployment_audit, self.metrics, self.structured_log = deployment_audit, metrics, structured_log
        self._closed = False
    def shutdown(self):
        if self._closed: return
        for dependency in (self.deployment_audit, self.metrics, self.structured_log):
            flush = getattr(dependency, "flush", None)
            if callable(flush): flush()
        self.canonical.database_credentials.close(); self._closed = True

def compose_production(config: InternalApiConfig, *, metrics, structured_log, identity_http_get, secrets_provider):
    if config.environment is not InternalApiEnvironment.PRODUCTION or config.build_metadata is None:
        raise ProductionStartupError("explicit production configuration is required")
    if not getattr(metrics, "production_safe", False) or not getattr(structured_log, "production_safe", False):
        raise ProductionStartupError("durable production observability adapters are required")
    if not getattr(secrets_provider, "homologation_safe", False):
        raise ProductionStartupError("external managed secret provider is required")
    homologation = replace(config, environment=InternalApiEnvironment.HOMOLOGATION, build_metadata=None)
    try:
        canonical = compose_homologation(homologation, metrics=metrics, structured_log=structured_log,
            identity_http_get=identity_http_get, secrets_provider=secrets_provider)
    except HomologationStartupError as exc:
        raise ProductionStartupError("canonical secure composition failed") from exc
    engine = canonical.database_credentials.engine
    build = config.build_metadata
    verifier = OfflineReplayVerifier(secrets_provider, config.offline_replay_database_credential,
        PostgreSQLOfflineReplayAudit(engine), require_tls=config.runtime_security.database_tls_required)
    try:
        verifier.verify(OfflineReplayRequest(OfflineReplayMode.STARTUP, build.release_id, build.build_id,
            build.source_revision, CURRENT_SCHEMA_REVISION, "production-startup", "startup:" + build.build_id))
    except OfflineReplayVerificationError as exc:
        canonical.database_credentials.close(); raise ProductionStartupError("offline replay verification failed") from exc
    del verifier
    checks = ProductionIntegrityVerifier(engine).check()
    if not checks or not all(item.ready for item in checks):
        canonical.database_credentials.close(); raise ProductionStartupError("production integrity self-check failed")
    audit = PostgreSQLDeploymentAudit(engine)
    if not audit.readiness().ready:
        canonical.database_credentials.close(); raise ProductionStartupError("deployment audit is unavailable")
    audit.append(deployment_event(config, CURRENT_SCHEMA_REVISION))
    safe_build = {**config.build_metadata.__dict__, "python_version": platform.python_version(),
                  "migration_revision": CURRENT_SCHEMA_REVISION}
    operations = replace(canonical.operational_services, build_metadata=safe_build)
    holder = {}
    @asynccontextmanager
    async def lifespan(_app):
        yield
        holder["composition"].shutdown()
    app = create_app(canonical.api_services, operations, runtime_security=config.runtime_security,
                     lifespan=lifespan, workspace=canonical.workspace,
                     remaining_workspace=canonical.remaining_workspace, launch_service=canonical.launch_service)
    composition = ProductionComposition(app, canonical, checks, audit, metrics, structured_log)
    holder["composition"] = composition
    app.state.production_composition = composition
    return composition
