"""Explicit NON-LIVE composition. Bound only by the local Compose deployment."""
import os
import json
from pathlib import Path
from dataclasses import replace
from contextlib import asynccontextmanager
import requests
from sqlalchemy.engine import URL
from jmoraIs.api.app import create_app
from jmoraIs.api.configuration import homologation_config, RuntimeSecurityPolicy
from jmoraIs.api.homologation import compose_homologation
from jmoraIs.api.security_infrastructure import InMemoryStructuredLog, InMemoryOpenTelemetryExporter, OpenTelemetryCompatibleMetricsAdapter
from jmoraIs.identity.configuration import OIDCProviderConfig
from jmoraIs.infrastructure.managed_secrets import ProviderReadySecretAdapter, InMemorySecretSecurityAudit
from jmoraIs.secrets.domain import KeyReference, SecretReference, SecretPurpose

PROVIDER='local-synthetic'
POLICY='MIP-10.1'
ISSUER='http://localhost:8081/realms/jmorais-local'
SIGNING=KeyReference(PROVIDER,'draft-signing','1',SecretPurpose.SIGNING_KEY)
PSEUDO=KeyReference(PROVIDER,'pseudonymization','1',SecretPurpose.PSEUDONYMIZATION_HMAC)
DATABASE=SecretReference(PROVIDER,'runtime-database',SecretPurpose.POSTGRESQL_CREDENTIALS,'1')


def guard():
    if os.environ.get('JMORAIS_LOCAL_SYNTHETIC')!='YES':
        raise RuntimeError('explicit synthetic-only deployment required')


def database_url(owner=False):
    guard()
    name=os.environ.get('LOCAL_DB_NAME')
    if not name:
        manifest=Path('/pilot-output/database.json')
        name=json.loads(manifest.read_text())['database'] if manifest.exists() else 'jmorais_local_synthetic'
    if not name.startswith('jmorais_local_synthetic'):raise RuntimeError('synthetic database required')
    return URL.create('postgresql+psycopg',username='pilot_owner' if owner else 'pilot_runtime',
        password=os.environ['LOCAL_DB_PASSWORD' if owner else 'LOCAL_RUNTIME_PASSWORD'],
        host='postgres',database=name).render_as_string(hide_password=False)


class LocalClient:
    def resolve(self, reference, version, purpose):
        guard()
        if version!='1': raise RuntimeError('unavailable key version')
        values={'runtime-database':(SecretPurpose.POSTGRESQL_CREDENTIALS,database_url()),
            'draft-signing':(SecretPurpose.SIGNING_KEY,os.environ['LOCAL_DRAFT_KEY']),
            'pseudonymization':(SecretPurpose.PSEUDONYMIZATION_HMAC,os.environ['LOCAL_PSEUDO_KEY'])}
        expected,value=values[reference]
        if purpose!=expected.value:raise RuntimeError('wrong key purpose')
        return value.encode()


def compose():
    guard()
    oidc=OIDCProviderConfig('local-keycloak',ISSUER,'jmorais-local',
        ISSUER+'/.well-known/openid-configuration',
        'http://oidc:8080/realms/jmorais-local/protocol/openid-connect/certs',
        ('RS256',),30,('sub','iat','exp','auth_time'),'roles','organization_id',
        (('reviewer','CLINICAL_REVIEWER'),('service','INTERNAL_SERVICE')),policy_version=POLICY)
    config=homologation_config(DATABASE,oidc,PSEUDO,governed_draft_signing_key=SIGNING)
    return compose_homologation(config,
        metrics=OpenTelemetryCompatibleMetricsAdapter(InMemoryOpenTelemetryExporter()),
        structured_log=InMemoryStructuredLog(),identity_http_get=requests.get,
        secrets_provider=ProviderReadySecretAdapter(PROVIDER,LocalClient(),InMemorySecretSecurityAudit()))


def create():
    canonical=compose()
    @asynccontextmanager
    async def lifespan(app):
        yield
        canonical.database_credentials.close()
    # HTTP is allowed only in this explicitly synthetic, loopback-published stack.
    app=create_app(canonical.api_services,canonical.operational_services,
        runtime_security=RuntimeSecurityPolicy(tls_termination_required=False,database_tls_required=False),
        lifespan=lifespan,workspace=canonical.workspace,remaining_workspace=canonical.remaining_workspace,
        launch_service=canonical.launch_service)
    # Evidence workbench behind the same OIDC bearer + IAM (CLINICAL_REVIEW, human reviewer).
    from jmoraIs.connect.crossref import CrossrefConnector
    from jmoraIs.connect.pubmed import PubMedConnector
    from jmoraIs.workbench.app import create_app as create_workbench, default_case_extractor_factory, default_classifier_factory, default_question_translator_factory, default_report_writer_factory, default_request_parser_factory, default_appeal_writer_factory
    from jmoraIs.application.appeal_library import AppealLibrary
    from jmoraIs.application.report_style import ReportStyleStore
    from jmoraIs.application.practice_documents import PracticeStore
    from jmoraIs.workbench.platform_auth import iam_authenticator
    # 10 most relevant results keep a live search inside the API's 30 s request budget.
    app.mount('/internal/evidence', create_workbench(pubmed=PubMedConnector(search_limit=10), crossref=CrossrefConnector(),
        resolve_classifier=lambda: default_classifier_factory(os.environ, keychain=lambda: None),
        resolve_case_extractor=lambda: default_case_extractor_factory(os.environ, keychain=lambda: None),
        tuss_index=_tuss_index(), catalog=_catalog(),
        resolve_question_translator=lambda: default_question_translator_factory(os.environ, keychain=lambda: None),
        resolve_report_writer=lambda: default_report_writer_factory(os.environ, keychain=lambda: None),
        resolve_request_parser=lambda: default_request_parser_factory(os.environ, keychain=lambda: None),
        report_style=ReportStyleStore(Path('/catalog/report_style.json')),
        sbot_index=_sbot_index(), practice=PracticeStore(Path('/catalog/practice.json')),
        appeal_library=AppealLibrary(Path('/catalog/appeals.json')),
        resolve_appeal_writer=lambda: default_appeal_writer_factory(os.environ, keychain=lambda: None),
        authenticate=iam_authenticator(canonical.operational_services)))
    return app


def _tuss_index():
    from jmoraIs.reference.tuss import TussIndex
    path=Path('/reference/tuss.sqlite')
    return TussIndex(path) if path.exists() else None


def _sbot_index():
    from jmoraIs.reference.sbot import SbotIndex
    path=Path('/reference/sbot.json')
    return SbotIndex(path) if path.exists() else None


def _catalog():
    from jmoraIs.application.surgical_catalog import CatalogStore, starter_templates
    store=CatalogStore(Path('/catalog/procedures.json'))
    store.seed(starter_templates(),_tuss_index())
    return store
