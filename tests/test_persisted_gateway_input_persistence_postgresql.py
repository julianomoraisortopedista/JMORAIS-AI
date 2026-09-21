import os
from dataclasses import replace
from datetime import datetime,timedelta,timezone
from uuid import uuid4
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine,text
from sqlalchemy.exc import DBAPIError
from jmoraIs.gateway_input import HMACPersistedGatewayInputAttestor,PersistedGatewayInputError
from jmoraIs.infrastructure.cryptographic_replay import PostgreSQLCryptographicReplayEngine,ReplayIntegrityStatus
from jmoraIs.infrastructure.managed_attestation import ManagedPersistedGatewayInputVerifier
from jmoraIs.infrastructure.managed_secrets import EphemeralSecretProvider,InMemoryKeyMetadataRepository
from jmoraIs.infrastructure.persisted_gateway_input import PostgreSQLPersistedGatewayInputRepository,PersistedGatewayInputTrustService
from jmoraIs.infrastructure.tenant_database import create_tenant_runtime_engine
from jmoraIs.llm_gateway import *
from jmoraIs.medical_documents import MedicalDocumentGatewayInputResolver,PostgreSQLMedicalDocumentRepository
from jmoraIs.medical_documents.gateway_input import MedicalDocumentGatewayInputIssuer
from jmoraIs.secrets.domain import KeyReference,KeyState,ManagedKeyMetadata,SecretPurpose,SecretReference
from jmoraIs.tenancy.context import TenantContextBinder
from jmoraIs.tenancy.domain import TenantContext
from tests.test_llm_gateway import request,response,template
from tests.test_medical_document_engine import setup as document_setup
pytestmark=pytest.mark.integration
NOW=datetime(2026,8,15,tzinfo=timezone.utc);KEY=b"postgres-persisted-input-signing-key-32-bytes"

def test_restart_backward_trace_rls_append_only_and_replay():
    url=os.getenv("JMORAIS_TEST_POSTGRES_URL")
    if not url:pytest.skip("JMORAIS_TEST_POSTGRES_URL is required")
    config=Config("alembic.ini");config.set_main_option("sqlalchemy.url",url);command.upgrade(config,"head")
    suffix=uuid4().hex;tenant=f"pgi-{suffix}";org=f"org-{suffix}";correlation=f"corr-{suffix}";owner=create_engine(url,future=True);binder=TenantContextBinder()
    trusted=TenantContext(tenant,org,"service","INTERNAL_SERVICE","CLINICAL_VALIDATION","MIP-10.1",correlation)
    other=TenantContext("other-"+suffix,"other-org-"+suffix,"service","INTERNAL_SERVICE","CLINICAL_VALIDATION","MIP-10.1","other-corr-"+suffix)
    with owner.begin() as c:
        for context in (trusted,other):c.execute(text("INSERT INTO tenants(tenant_id,organization_id,display_name,status,policy_version,created_at) VALUES(:t,:o,'PGI','ACTIVE','MIP-10.1',:at)"),{"t":context.tenant_id,"o":context.organization_id,"at":NOW})
    writer=create_tenant_runtime_engine(url,runtime_role="jmorais_application_writer")
    engine,_,_,inp=document_setup();version=engine.generate(inp,__import__("jmoraIs.medical_documents",fromlist=["DocumentType"]).DocumentType.CLINICAL_REPORT);version=replace(version,version_id="doc_"+uuid4().hex*2,document_stream_id="doc_"+uuid4().hex*2)
    with binder.bind_tenant(trusted):PostgreSQLMedicalDocumentRepository(writer).append(version)
    key=KeyReference("memory","gateway-input-"+suffix,"v1",SecretPurpose.SIGNING_KEY);secret=SecretReference("memory",key.key_id,SecretPurpose.SIGNING_KEY,"v1")
    provider=EphemeralSecretProvider({(key.key_id,"v1"):(secret,KEY)});metadata=InMemoryKeyMetadataRepository((ManagedKeyMetadata(key,KeyState.ACTIVE,NOW,NOW,None,None,"keys-v1"),));verifier=ManagedPersistedGatewayInputVerifier(provider,metadata)
    attestor=HMACPersistedGatewayInputAttestor(KEY);repository=PostgreSQLPersistedGatewayInputRepository(writer,verifier)
    with binder.bind_tenant(trusted):bound=MedicalDocumentGatewayInputIssuer(PostgreSQLMedicalDocumentRepository(writer),attestor,clock=lambda:NOW,key_reference=key).issue(version.document_stream_id,version.version)
    conflicting=MedicalDocumentGatewayInputIssuer(PostgreSQLMedicalDocumentRepository(writer),attestor,clock=lambda:NOW+timedelta(seconds=1),key_reference=key)
    with binder.bind_tenant(trusted):conflicting=conflicting.issue(version.document_stream_id,version.version)
    with binder.bind_tenant(trusted):conflicting_id=__import__("jmoraIs.gateway_input",fromlist=["persisted_gateway_input_record"]).persisted_gateway_input_record(conflicting).persisted_gateway_input_id
    conflicting_stream=trusted.tenant_id+"|"+conflicting_id
    with owner.begin() as c:c.execute(text("INSERT INTO cryptographic_stream_checkpoints(stream_namespace,stream_id,stream_position,head_hash,recorded_at) VALUES('persisted_gateway_inputs',:id,1,:hash,:at)"),{"id":conflicting_stream,"hash":"0"*64,"at":NOW})
    with binder.bind_tenant(trusted),pytest.raises(DBAPIError):repository.append(conflicting)
    with owner.connect() as c:assert c.execute(text("SELECT count(*) FROM persisted_gateway_inputs WHERE persisted_gateway_input_id=:id"),{"id":conflicting_id}).scalar_one()==0
    with owner.begin() as c:
        c.execute(text("ALTER TABLE cryptographic_stream_checkpoints DISABLE TRIGGER ALL"));c.execute(text("DELETE FROM cryptographic_stream_checkpoints WHERE stream_namespace='persisted_gateway_inputs' AND stream_id=:id"),{"id":conflicting_stream});c.execute(text("ALTER TABLE cryptographic_stream_checkpoints ENABLE TRIGGER ALL"))
    invalid=replace(conflicting,attestation="0"*64)
    with binder.bind_tenant(trusted),pytest.raises(PersistedGatewayInputError):repository.append(invalid)
    with owner.connect() as c:assert c.execute(text("SELECT count(*) FROM cryptographic_stream_checkpoints WHERE stream_namespace='persisted_gateway_inputs' AND stream_id=:id"),{"id":conflicting_stream}).scalar_one()==0
    prompt_template=replace(template(("MedicalDocument",)),template_id="pgi-template-"+suffix,name="PGI "+suffix)
    prompts=PostgreSQLPromptRepository(owner);registration=PostgreSQLPromptAuditRepository(owner);prompt=PromptGovernanceService(prompts,registration,clock=lambda:NOW).register(prompt_template,created_by="service")
    invocations=PostgreSQLInvocationRepository(writer);contexts=PostgreSQLLLMInvocationContextRepository(writer);audits=PostgreSQLPromptAuditRepository(writer)
    gateway=CanonicalLLMGateway(prompts,audits,invocations,contexts,(MockProviderAdapter((response(),)),),clock=lambda:NOW,persisted_input_attestor=attestor,persisted_inputs=repository)
    request_id="request-pgi-"+suffix
    with binder.bind_tenant(trusted):
        gateway.invoke_persisted(request(prompt,input_dto=bound,request_id=request_id));invocation=invocations.history(request_id)[0]
        assert invocation.persisted_gateway_input_id and repository.get_by_request(request_id).persisted_gateway_input_id==invocation.persisted_gateway_input_id
    writer.dispose();owner.dispose();del gateway,repository,bound,invocations,contexts,audits
    restarted_owner=create_engine(url,future=True);reader=create_tenant_runtime_engine(url,runtime_role="jmorais_application_reader")
    restarted_repo=PostgreSQLPersistedGatewayInputRepository(reader,verifier)
    with binder.bind_tenant(trusted):
        reread_invocation=PostgreSQLInvocationRepository(reader).history(request_id)[0]
        record=restarted_repo.get_by_invocation(reread_invocation.invocation_id)
        reconstructed=PersistedGatewayInputTrustService(restarted_repo,verifier,{"MedicalDocument":MedicalDocumentGatewayInputResolver(PostgreSQLMedicalDocumentRepository(reader))}).verify_and_resolve(record.persisted_gateway_input_id)
    assert reread_invocation.persisted_gateway_input_id==record.persisted_gateway_input_id
    assert reconstructed.reference.artifact_version==version.version and reconstructed.dto==version.document
    with binder.bind_tenant(other):assert restarted_repo.get(record.persisted_gateway_input_id) is None
    with pytest.raises(Exception,match="tenant context"):restarted_repo.get(record.persisted_gateway_input_id)
    with restarted_owner.connect() as c:assert not c.execute(text("SELECT rolbypassrls FROM pg_roles WHERE rolname='jmorais_application_reader'")).scalar_one()
    with pytest.raises(DBAPIError),restarted_owner.begin() as c:c.execute(text("UPDATE persisted_gateway_inputs SET dto_hash=:hash WHERE persisted_gateway_input_id=:id"),{"hash":"0"*64,"id":record.persisted_gateway_input_id})
    with pytest.raises(DBAPIError),restarted_owner.begin() as c:c.execute(text("DELETE FROM persisted_gateway_inputs WHERE persisted_gateway_input_id=:id"),{"id":record.persisted_gateway_input_id})
    assert PostgreSQLCryptographicReplayEngine(restarted_owner).replay_persisted_gateway_input(record.persisted_gateway_input_id).integrity_status is ReplayIntegrityStatus.VALID
    checkpoint_stream=trusted.tenant_id+"|"+record.persisted_gateway_input_id
    with restarted_owner.connect() as c:
        checkpoint=c.execute(text("SELECT stream_position,head_hash FROM cryptographic_stream_checkpoints WHERE stream_namespace='persisted_gateway_inputs' AND stream_id=:id"),{"id":checkpoint_stream}).mappings().one()
    assert checkpoint=={"stream_position":1,"head_hash":record.integrity_hash}
    global_report=PostgreSQLCryptographicReplayEngine(restarted_owner).replay_all()
    current=next(item for item in global_report.streams if item.stream==f"persisted_gateway_inputs:{trusted.tenant_id}:{record.persisted_gateway_input_id}")
    assert current.integrity_status is ReplayIntegrityStatus.VALID and current.completeness_verified
    assert current.checkpoint_found and current.expected_records==current.observed_records==1

    # A privileged full-record deletion cannot erase the independently anchored
    # expectation. Restore only after observing replay_all(), keeping test data isolated.
    with restarted_owner.connect() as c:
        c.execute(text("CREATE TEMP TABLE saved_pgi AS SELECT * FROM persisted_gateway_inputs WHERE persisted_gateway_input_id=:id"),{"id":record.persisted_gateway_input_id});c.commit()
        c.execute(text("ALTER TABLE persisted_gateway_inputs DISABLE TRIGGER ALL"));c.execute(text("DELETE FROM persisted_gateway_inputs WHERE persisted_gateway_input_id=:id"),{"id":record.persisted_gateway_input_id});c.execute(text("ALTER TABLE persisted_gateway_inputs ENABLE TRIGGER ALL"));c.commit()
        deleted_report=PostgreSQLCryptographicReplayEngine(restarted_owner).replay_all()
        deleted=next(item for item in deleted_report.streams if item.stream==f"persisted_gateway_inputs:{trusted.tenant_id}:{record.persisted_gateway_input_id}")
        assert deleted_report.overall_decision is ReplayIntegrityStatus.TAMPERED and not deleted.completeness_verified
        assert deleted.checkpoint_found and deleted.observed_records==0
        c.execute(text("ALTER TABLE persisted_gateway_inputs DISABLE TRIGGER ALL"));c.execute(text("INSERT INTO persisted_gateway_inputs SELECT * FROM saved_pgi"));c.execute(text("ALTER TABLE persisted_gateway_inputs ENABLE TRIGGER ALL"));c.commit()

    # A surviving new record without its required checkpoint is likewise legacy-
    # ineligible and fail-closed. The immutable checkpoint is restored afterward.
    with restarted_owner.connect() as c:
        c.execute(text("CREATE TEMP TABLE saved_pgi_checkpoint AS SELECT * FROM cryptographic_stream_checkpoints WHERE stream_namespace='persisted_gateway_inputs' AND stream_id=:id"),{"id":checkpoint_stream});c.commit()
        c.execute(text("ALTER TABLE cryptographic_stream_checkpoints DISABLE TRIGGER ALL"));c.execute(text("DELETE FROM cryptographic_stream_checkpoints WHERE stream_namespace='persisted_gateway_inputs' AND stream_id=:id"),{"id":checkpoint_stream});c.execute(text("ALTER TABLE cryptographic_stream_checkpoints ENABLE TRIGGER ALL"));c.commit()
        missing_report=PostgreSQLCryptographicReplayEngine(restarted_owner).replay_all()
        missing=next(item for item in missing_report.streams if item.stream==f"persisted_gateway_inputs:{trusted.tenant_id}:{record.persisted_gateway_input_id}")
        assert missing_report.overall_decision is ReplayIntegrityStatus.TAMPERED and not missing.checkpoint_found
        c.execute(text("ALTER TABLE cryptographic_stream_checkpoints DISABLE TRIGGER ALL"));c.execute(text("INSERT INTO cryptographic_stream_checkpoints SELECT * FROM saved_pgi_checkpoint"));c.execute(text("ALTER TABLE cryptographic_stream_checkpoints ENABLE TRIGGER ALL"));c.commit()
    reader.dispose();restarted_owner.dispose()
