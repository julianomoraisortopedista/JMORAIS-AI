"""NON-LIVE subprocess composition fixture. Never a pilot deployment factory."""
import json
import os
from dataclasses import replace
from pathlib import Path
from sqlalchemy.engine import make_url
from jmoraIs.api.configuration import InternalApiEnvironment, BuildMetadata, RuntimeSecurityPolicy
from jmoraIs.api.production import compose_production
from jmoraIs.infrastructure.managed_secrets import ProviderReadySecretAdapter, InMemorySecretSecurityAudit
from jmoraIs.secrets.domain import SecretReference, SecretPurpose
from tests import test_api_homologation_postgresql as rt
from tests import test_governed_draft_signing_binding as binding


def create():
    url=os.environ['JMORAIS_TEST_POSTGRES_URL']
    if not (make_url(url).database or '').startswith('pilot_release_'):
        raise RuntimeError('isolated pilot_release test database required')
    policy=os.environ['JMORAIS_PILOT_FIXTURE_POLICY']
    jwks=json.loads(Path(os.environ['JMORAIS_PILOT_FIXTURE_JWKS']).read_text())
    class Response:
        def raise_for_status(self): pass
        def json(self): return jwks
    class Secrets(rt.SecretClient):
        def resolve(self,reference,version,purpose):
            if reference=='offline-verifier':return self.database_url.encode()
            return super().resolve(reference,version,purpose)
    config=binding.config()
    config=replace(config,environment=InternalApiEnvironment.PRODUCTION,
        oidc=replace(config.oidc,policy_version=policy,
            role_mapping=(('reviewer','CLINICAL_REVIEWER'),('service','INTERNAL_SERVICE'),('admin','ADMINISTRATOR'))),
        build_metadata=BuildMetadata('pilot-fixture','pilot-build','396e937ca850fe63085eb38752d2c651daf070fe',rt.NOW.isoformat()),
        offline_replay_database_credential=SecretReference('test-vault','offline-verifier',SecretPurpose.OFFLINE_REPLAY_DATABASE_CREDENTIAL,'1'),
        runtime_security=RuntimeSecurityPolicy(database_tls_required=False))
    return compose_production(config,
        metrics=binding.Metrics(rt.InMemoryOpenTelemetryExporter()),structured_log=binding.Logs(),
        secrets_provider=ProviderReadySecretAdapter('test-vault',Secrets(url),InMemorySecretSecurityAudit()),
        identity_http_get=lambda *_a,**_k:Response())
