"""Prospective synthetic data using existing owner fixtures; no clinical backfill."""
from dataclasses import replace
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import time
from uuid import uuid4
import requests
from sqlalchemy import create_engine,text
from alembic import command
from alembic.config import Config
from fastapi.encoders import jsonable_encoder
from jmoraIs.api.security import CallerContext,CallerRole,PurposeOfUse
from jmoraIs.api.workspace_launch import LaunchReferences
from jmoraIs.identity.domain import ExternalIdentityLink,IdentityLinkStatus,PrincipalType
from jmoraIs.infrastructure.identity_persistence import PostgreSQLExternalIdentityLinkRepository
from jmoraIs.infrastructure.secret_persistence import PostgreSQLKeyMetadataRepository
from jmoraIs.secrets.domain import ManagedKeyMetadata,KeyState
from jmoraIs.tenancy.domain import TenantContext
from jmoraIs.tenancy.context import TenantContextBinder
from deploy.local.runtime import database_url,compose,SIGNING,PSEUDO,POLICY


def main():
    for _ in range(120):
        try:
            if requests.get('http://oidc:8080/realms/jmorais-local/.well-known/openid-configuration',timeout=2).status_code==200:break
        except requests.RequestException:pass
        time.sleep(2)
    else:raise RuntimeError('local OIDC unavailable')
    # Local public PKCE client uses signing only. Disable the unused encryption
    # provider at its owner, rather than filtering/bypassing backend JWKS checks.
    response=requests.post('http://oidc:8080/realms/master/protocol/openid-connect/token',
        data={'grant_type':'password','client_id':'admin-cli','username':'local-admin',
              'password':os.environ['LOCAL_OIDC_ADMIN_PASSWORD']},timeout=10)
    response.raise_for_status()
    headers={'Authorization':'Bearer '+response.json()['access_token']}
    admin='http://oidc:8080/admin/realms/jmorais-local'
    response=requests.get(admin+'/components',headers=headers,timeout=10)
    response.raise_for_status()
    for component in response.json():
        if component.get('providerId')=='rsa-enc-generated':
            component['config'].update(enabled=['false'],active=['false'])
            response=requests.put(admin+'/components/'+component['id'],headers=headers,json=component,timeout=10)
            response.raise_for_status()
    del headers
    output=Path('/pilot-output')
    if (output/'complete.json').exists():
        print('SYNTHETIC_SEED_ALREADY_PRESENT');return
    # Failed attempts remain isolated; publish only a completely validated database.
    base=create_engine(database_url(True),isolation_level='AUTOCOMMIT')
    name='jmorais_local_synthetic_'+uuid4().hex
    with base.connect() as c:
        from psycopg import sql
        c.connection.driver_connection.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    base.dispose()
    os.environ['LOCAL_DB_NAME']=name
    url=database_url(True)
    cfg=Config('alembic.ini');cfg.set_main_option('sqlalchemy.url',url.replace('%','%%'))
    command.upgrade(cfg,'head')
    owner=create_engine(url)
    with owner.begin() as c:
        if not c.execute(text("SELECT 1 FROM pg_roles WHERE rolname='pilot_runtime'")).scalar():
            from psycopg import sql
            c.connection.driver_connection.execute(sql.SQL('CREATE ROLE pilot_runtime LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD {}').format(sql.Literal(os.environ['LOCAL_RUNTIME_PASSWORD'])))
        c.execute(text('GRANT jmorais_application_writer,jmorais_application_reader TO pilot_runtime'))
    output=Path('/pilot-output')
    if (output/'complete.json').exists():
        owner.dispose();print('SYNTHETIC_SEED_ALREADY_PRESENT');return
    now=datetime.now(timezone.utc)
    tenant=TenantContext('synthetic-tenant','synthetic-org','synthetic-producer','INTERNAL_SERVICE',
        'CLINICAL_VALIDATION',POLICY,'synthetic-seed')
    with owner.begin() as c:
        existing=c.execute(text('SELECT organization_id,policy_version FROM tenants WHERE tenant_id=:t'),{'t':tenant.tenant_id}).one_or_none()
        if existing is not None and tuple(existing)!=(tenant.organization_id,POLICY):raise RuntimeError('synthetic tenant mismatch')
        c.execute(text("INSERT INTO tenants(tenant_id,organization_id,display_name,status,policy_version,created_at) VALUES(:t,:o,'SYNTHETIC LOCAL ONLY','ACTIVE',:p,:at) ON CONFLICT (tenant_id) DO NOTHING"),dict(t=tenant.tenant_id,o=tenant.organization_id,p=POLICY,at=now))
    for key in (SIGNING,PSEUDO):
        PostgreSQLKeyMetadataRepository(owner).save(ManagedKeyMetadata(key,KeyState.ACTIVE,now,now,None,None,'local-synthetic'))
    for subject,kind,purpose in [('synthetic-physician',PrincipalType.HUMAN,'CLINICAL_REVIEW'),('synthetic-operations',PrincipalType.SERVICE,'INTERNAL_OPERATIONS')]:
        links=PostgreSQLExternalIdentityLinkRepository(owner)
        existing=links.get('local-keycloak',subject)
        if existing is not None:
            if (existing.tenant_id,existing.organization_id,existing.allowed_purposes)!=(tenant.tenant_id,tenant.organization_id,(purpose,)):raise RuntimeError('synthetic identity mismatch')
            continue
        links.create(ExternalIdentityLink(subject,'local-keycloak',subject,
            tenant.organization_id,tenant.tenant_id,IdentityLinkStatus.ACTIVE,kind,(purpose,),('api:read',),None,now,now,POLICY))
    canonical=compose()
    writer=canonical.database_credentials.engine
    # Reuse approved synthetic owner builders only, never their mock auth/runtime.
    from deploy.local import synthetic_core as core
    from tests import test_audit_defense_reference_states_postgresql as defense
    from tests import test_governed_llm_draft_exact_reference_postgresql as drafts
    from tests import test_human_review_exact_reference_postgresql as review
    physician=CallerContext('synthetic-physician',CallerRole.CLINICAL_REVIEWER,PurposeOfUse.CLINICAL_REVIEW,
        'synthetic-launch',POLICY,organization_id=tenant.organization_id,tenant_id=tenant.tenant_id,principal_type='HUMAN',scoped_permissions=('api:read',))
    for index in range(1,4):
        suffix=uuid4().hex
        with TenantContextBinder().bind_tenant(tenant):
            reasoning,timeline=core.seed(owner,writer,tenant,suffix)
            state=reasoning.clinical_state_reference
            document=replace(defense.document_value(),version_id='doc_'+uuid4().hex*2,document_stream_id='doc_'+uuid4().hex*2)
            defense.PostgreSQLMedicalDocumentRepository(writer).append(document)
            documents=defense.PostgreSQLMedicalDocumentExactReferenceRepository(writer)
            document_ref=documents.reference_for(document)
            service,_,_,inp=defense.defense_setup()
            package=replace(service.generate(inp),package_id='def_'+uuid4().hex*2,stream_id='def_'+uuid4().hex*2)
            defenses=defense.PostgreSQLAuditDefenseRepository(writer);defenses.append(package)
            pre=defenses.reference_for_pre_link(package)
            linked=defense.AuditDefenseTraceabilityService(documents,defenses,defense.PostgreSQLAuditDefenseEventAdapter(writer),clock=lambda:defense.NOW).link_stage11_document(pre,document_ref)
            draft,attestor,_,invocation=drafts.persisted_draft(owner,writer,suffix,tenant,draft_attestor=canonical.draft_attestor,
                subject_reference='pt_'+suffix*2)
            invocations=review.PostgreSQLLLMInvocationExactReferenceRepository(writer)
            invocation_ref=invocations.reference_for(invocation)
            draft_repo=review.PostgreSQLGovernedLLMDraftExactReferenceRepository(writer,attestor,invocation_references=invocations)
            draft_ref=draft_repo.reference_for(draft,invocation_ref)
            unsigned=review.LLMHumanReviewEvent('review-'+suffix,draft.draft_id,draft.version,draft.invocation_id,
                draft.request_id,draft.correlation_id,tenant.tenant_id,draft.upstream_artifact_reference,
                review.HumanReviewStatus.PENDING_REVIEW,review.HumanReviewStatus.APPROVED_BY_REVIEWER,
                review.LLMReviewDecision.APPROVE,'synthetic-reviewer',review.ReviewerRole.REVIEWER,
                tenant.organization_id,'ST-15.1','SYNTHETIC DEMONSTRATION ONLY',review.NOW,1,None,None,'')
            reviewed=replace(unsigned,integrity_hash=review.review_event_hash(unsigned))
            review.PostgreSQLLLMHumanReviewRepository(writer).append(reviewed)
            reviewed_ref=review.PostgreSQLHumanReviewExactReferenceRepository(writer,draft_repo).reference_for(reviewed,draft_ref)
            refs=LaunchReferences.model_validate(jsonable_encoder(dict(summary=state,timeline=timeline,
                evidence=reasoning.governed_evidence_references[0],explainability=reasoning,
                medical_document=document_ref,human_review=reviewed_ref,audit_defense=linked)))
        with TenantContextBinder().bind(physician):launch=canonical.launch_producer.create(physician,refs)
        path=output/f'patient-{index}-launch.json'
        path.write_text(launch.model_dump_json());path.chmod(0o600)
    from jmoraIs.infrastructure.cryptographic_replay import PostgreSQLCryptographicReplayEngine
    report=PostgreSQLCryptographicReplayEngine(owner).replay_all()
    if report.overall_decision.value!='VALID':raise RuntimeError('seed replay invalid')
    (output/'database.json').write_text(json.dumps({'database':name}))
    (output/'complete.json').write_text(json.dumps({'synthetic':True,'patients':3}))
    canonical.database_credentials.close();owner.dispose()
    print('SYNTHETIC_SEED_CREATED')


if __name__=='__main__':
    try:main()
    except Exception as exc:
        print('SEED_FAILED: '+type(exc).__name__)
        import traceback
        print('LOCATION: '+ ' -> '.join(f'{Path(frame.filename).name}:{frame.lineno}:{frame.name}' for frame in traceback.extract_tb(exc.__traceback__)))
        raise SystemExit(1)
