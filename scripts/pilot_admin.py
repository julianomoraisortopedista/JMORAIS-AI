"""Explicit tenant-scoped operator actions through existing IAM and owner services."""
from contextlib import nullcontext
from datetime import datetime, timezone
import argparse
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

# Direct script invocation must resolve the installed project's public packages.
from jmoraIs.api.production_asgi import create
from jmoraIs.api.security import CallerCredentials, CallerRole, PurposeOfUse
from jmoraIs.api.workspace_launch import LaunchReferences
from jmoraIs.identity.application import IdentityLinkService
from jmoraIs.identity.domain import ExternalIdentityLink, IdentityLinkStatus, PrincipalType
from jmoraIs.infrastructure.identity_persistence import PostgreSQLExternalIdentityLinkRepository, PostgreSQLIdentitySecurityAudit
from jmoraIs.infrastructure.tenant_persistence import PostgreSQLTenantRepository
from jmoraIs.tenancy.context import TenantContextBinder
from jmoraIs.tenancy.domain import TenantStatus
from scripts.pilot import PilotRejected, token_input, ROOT


def provision(canonical, caller, data):
    fields={'provider','external_subject','principal_id','organization_id','tenant_id','policy_version'}
    if set(data)!=fields or any(not isinstance(value,str) or not value.strip() for value in data.values()):
        raise PilotRejected('EXPLICIT_IDENTITY_METADATA_REQUIRED')
    if (caller.role is not CallerRole.ADMINISTRATOR or caller.purpose is not PurposeOfUse.ADMINISTRATION
        or caller.principal_type!='HUMAN'):
        raise PilotRejected('AUTHENTICATED_HUMAN_ADMINISTRATION_REQUIRED')
    if (data['tenant_id'],data['organization_id'],data['policy_version']) != (
        caller.tenant_id,caller.organization_id,caller.policy_version):
        raise PilotRejected('CROSS_TENANT_PROVISIONING_FORBIDDEN')
    with TenantContextBinder().bind(caller):
        engine=canonical.database_credentials.engine
        tenant=PostgreSQLTenantRepository(engine).get(caller.tenant_id)
        if (tenant is None or tenant.status is not TenantStatus.ACTIVE or
            (tenant.organization_id,tenant.policy_version)!=(caller.organization_id,caller.policy_version)):
            raise PilotRejected('EXISTING_ACTIVE_TENANT_REQUIRED')
        now=datetime.now(timezone.utc)
        link=ExternalIdentityLink(data['principal_id'],data['provider'],data['external_subject'],
            tenant.organization_id,tenant.tenant_id,IdentityLinkStatus.ACTIVE,PrincipalType.HUMAN,
            ('CLINICAL_REVIEW',),('api:read',),None,now,now,tenant.policy_version)
        # Existing service and audit share one transaction; no unaudited partial link.
        with engine.begin() as connection:
            class Transaction:
                def begin(self):return nullcontext(connection)
            scope=Transaction()
            IdentityLinkService(PostgreSQLExternalIdentityLinkRepository(scope),
                PostgreSQLIdentitySecurityAudit(scope),clock=lambda:now).create(link,correlation_id=caller.correlation_id)
    return link


def private_output(path):
    target = Path(path)
    if not target.is_absolute() or target.resolve().is_relative_to(ROOT):
        raise PilotRejected('LAUNCH_OUTPUT_MUST_BE_OUTSIDE_REPOSITORY')
    return os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=('link-physician','create-launch'))
    parser.add_argument('--input',required=True,help='Explicit metadata or existing typed owner references; no tokens')
    parser.add_argument('--output',help='New private output file for the exact launch reference')
    parser.add_argument('--token-stdin',action='store_true')
    args=parser.parse_args()
    composition=None
    try:
        if os.getenv('JMORAIS_PRODUCTION_COMPOSITION_FACTORY','').startswith('tests.'):
            raise PilotRejected('REAL_PRODUCTION_FACTORY_REQUIRED')
        data=json.loads(Path(args.input).read_text())
        bearer=token_input(args.token_stdin)
        app=create()
        composition=app.state.production_composition
        canonical=composition.canonical
        purpose='ADMINISTRATION' if args.action=='link-physician' else 'CLINICAL_REVIEW'
        caller=canonical.operational_services.authentication.authenticate(CallerCredentials(bearer,purpose),uuid4().hex)
        if args.action=='link-physician':provision(canonical,caller,data)
        else:
            if not args.output:raise PilotRejected('EXCLUSIVE_PRIVATE_OUTPUT_REQUIRED')
            # Reserve output before creating authorization; never overwrite an existing launch.
            fd=private_output(args.output)
            with os.fdopen(fd,'w') as output, TenantContextBinder().bind(caller):
                reference=canonical.launch_producer.create(caller,LaunchReferences.model_validate(data))
                output.write(reference.model_dump_json())
        print(json.dumps({'STATUS':'PASS','ACTION':args.action,'CLINICAL_MUTATION':False}))
        return 0
    except Exception as exc:
        print(json.dumps({'STATUS':'REJECTED','REASON':str(exc) if isinstance(exc,PilotRejected) else type(exc).__name__}))
        return 1
    finally:
        if composition is not None:composition.shutdown()


if __name__=='__main__':raise SystemExit(main())
