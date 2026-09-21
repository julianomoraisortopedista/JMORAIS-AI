from __future__ import annotations
from typing import Protocol
from .models import *

class PersistedStagePort(Protocol):
    stage:AcceptanceStage
    def execute(self, identity:E2ECaseIdentity, preceding:StageExecution|None)->object: ...
    def persist(self, artifact:object)->None: ...
    def release(self)->None: ...
    def reread(self, reference_id:str, version:str)->object|None: ...
    def describe(self, artifact:object)->StageExecution: ...

class AcceptanceHarnessError(RuntimeError): pass

class CanonicalE2EAcceptanceHarness:
    """Test-only coordinator. Stage adapters own all bounded-context behavior."""
    def __init__(self, stages:tuple[PersistedStagePort,...], manifest_repository, *, clock):
        if tuple(x.stage for x in stages)!=tuple(AcceptanceStage):
            raise AcceptanceHarnessError("every canonical stage must be present exactly once and in order")
        self._stages,self._manifests,self._clock=stages,manifest_repository,clock
    def run(self, identity:E2ECaseIdentity)->AcceptanceResult:
        records=[]; preceding=None
        for adapter in self._stages:
            artifact=adapter.execute(identity,preceding); adapter.persist(artifact); described=adapter.describe(artifact)
            if described.stage is not adapter.stage or not described.reference_id or not described.version or not described.provenance_references:
                raise AcceptanceHarnessError(f"incomplete persisted handoff at {adapter.stage.value}")
            adapter.release()
            exact_reread=getattr(adapter,"reread_exact",None)
            persisted=exact_reread(artifact) if callable(exact_reread) else adapter.reread(described.reference_id,described.version)
            if persisted is None: raise AcceptanceHarnessError(f"persisted handoff unavailable at {adapter.stage.value}")
            records.append(described); preceding=described
            if described.status in {ExecutionStatus.BLOCKED,ExecutionStatus.FAILED}:
                break
        manifest=E2ETraceManifest(identity.execution_id,identity.case_id,identity.tenant_id,
            identity.correlation_id,tuple(records),identity.policy_versions,self._clock())
        self._manifests.append(manifest)
        status=ExecutionStatus.COMPLETED if manifest.complete else records[-1].status
        return AcceptanceResult(identity,status,manifest)
    def reconstruct(self,execution_id:str): return self._manifests.get(execution_id)
