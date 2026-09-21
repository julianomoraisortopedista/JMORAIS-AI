from dataclasses import replace
from datetime import datetime,timezone
import pytest
from jmoraIs.gateway_input import HMACPersistedGatewayInputAttestor,PersistedGatewayInputError
from jmoraIs.infrastructure.managed_attestation import ManagedPersistedGatewayInputVerifier
from jmoraIs.infrastructure.managed_secrets import EphemeralSecretProvider,InMemoryKeyMetadataRepository
from jmoraIs.infrastructure.persisted_gateway_input import InMemoryPersistedGatewayInputRepository,PersistedGatewayInputTrustService,PostgreSQLPersistedGatewayInputRepository,_encode
from jmoraIs.medical_documents import MedicalDocumentGatewayInputResolver
from jmoraIs.medical_documents.gateway_input import MedicalDocumentGatewayInputIssuer
from jmoraIs.secrets.domain import KeyReference,KeyState,ManagedKeyMetadata,SecretPurpose,SecretReference
from jmoraIs.tenancy.context import TenantContextBinder
from jmoraIs.tenancy.domain import TenantContext
from tests.test_medical_document_engine import setup as document_setup
NOW=datetime(2026,8,15,tzinfo=timezone.utc);KEY=b"managed-persisted-input-signing-key-32-bytes"
REF=KeyReference("memory","gateway-input","v1",SecretPurpose.SIGNING_KEY)
def verifier(state=KeyState.ACTIVE,available=True):
    secret=SecretReference("memory","gateway-input",SecretPurpose.SIGNING_KEY,"v1");provider=EphemeralSecretProvider({("gateway-input","v1"):(secret,KEY)});provider.available=available
    metadata=InMemoryKeyMetadataRepository((ManagedKeyMetadata(REF,state,NOW,NOW,None,NOW if state is KeyState.REVOKED else None,"keys-v1"),))
    return ManagedPersistedGatewayInputVerifier(provider,metadata)
@pytest.fixture(autouse=True)
def tenant():
    with TenantContextBinder().bind_tenant(TenantContext("tenant-test","org-test","service","INTERNAL_SERVICE","CLINICAL_VALIDATION","MIP-10.1","correlation-test")):yield
def bound():
    engine,documents,_,inp=document_setup();version=engine.generate(inp,__import__("jmoraIs.medical_documents",fromlist=["DocumentType"]).DocumentType.CLINICAL_REPORT)
    value=MedicalDocumentGatewayInputIssuer(documents,HMACPersistedGatewayInputAttestor(KEY),clock=lambda:NOW,key_reference=REF).issue(version.document_stream_id,version.version)
    return value,version,documents
def test_metadata_only_record_and_restart_style_trust_reconstruction():
    value,version,documents=bound();repository=InMemoryPersistedGatewayInputRepository(verifier());record=repository.append(value)
    assert record.dto_hash==value.dto_hash and not hasattr(record,"dto")
    assert "sections" not in repr(record) and repository.get(record.persisted_gateway_input_id)==record
    reconstructed=PersistedGatewayInputTrustService(repository,verifier(),{"MedicalDocument":MedicalDocumentGatewayInputResolver(documents)}).verify_and_resolve(record.persisted_gateway_input_id)
    assert reconstructed==value and reconstructed.dto==version.document
def test_forgery_hash_key_tenant_and_upstream_fail_closed():
    value,_,documents=bound()
    for invalid in (replace(value,attestation="0"*64),replace(value,dto_hash="0"*64),replace(value,attestation_key_reference=None),replace(value,reference=replace(value.reference,source_context=""))):
        with pytest.raises(PersistedGatewayInputError):InMemoryPersistedGatewayInputRepository(verifier()).append(invalid)
    with pytest.raises(PersistedGatewayInputError):InMemoryPersistedGatewayInputRepository(verifier(KeyState.REVOKED)).append(value)
    with pytest.raises(PersistedGatewayInputError):InMemoryPersistedGatewayInputRepository(verifier(available=False)).append(value)
    record=InMemoryPersistedGatewayInputRepository(verifier()).append(value)
    with pytest.raises(PersistedGatewayInputError):PersistedGatewayInputTrustService(InMemoryPersistedGatewayInputRepository(verifier()),verifier(),{}).verify_and_resolve(record.persisted_gateway_input_id)

def test_relational_payload_and_record_integrity_mismatch_fail_closed():
    value,_,_=bound();record=InMemoryPersistedGatewayInputRepository(verifier()).append(value);r=record.upstream_artifact_reference;k=record.attestation_key_reference
    row={"persisted_gateway_input_id":record.persisted_gateway_input_id,"tenant_id":r.tenant_id,"artifact_type":r.artifact_type,
         "artifact_id":r.artifact_id,"artifact_version":r.artifact_version,"source_context":r.source_context,
         "integrity_reference":r.integrity_reference,"policy_version":r.policy_version,"dto_hash":record.dto_hash,
         "issued_at":record.issued_at,"attestation":record.attestation,"key_provider":k.provider,"key_id":k.key_id,
         "key_version":k.version,"record_integrity_hash":record.integrity_hash,"payload":_encode(record),"schema_version":1}
    assert PostgreSQLPersistedGatewayInputRepository._checked(row)==record
    with pytest.raises(PersistedGatewayInputError):PostgreSQLPersistedGatewayInputRepository._checked({**row,"dto_hash":"0"*64})
    bad_payload={**row["payload"],"integrity_hash":"0"*64}
    with pytest.raises(PersistedGatewayInputError):PostgreSQLPersistedGatewayInputRepository._checked({**row,"payload":bad_payload,"record_integrity_hash":"0"*64})
