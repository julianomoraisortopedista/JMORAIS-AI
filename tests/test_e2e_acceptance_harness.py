from datetime import datetime,timezone
import pytest
from evaluation.e2e_acceptance import *

NOW=datetime(2026,8,10,tzinfo=timezone.utc)
class MemoryManifests:
    def __init__(self):self.items={}
    def append(self,value):
        if value.execution_id in self.items:raise RuntimeError("append-only")
        self.items[value.execution_id]=value
    def get(self,key):return self.items.get(key)
class Stage:
    def __init__(self,stage,status=ExecutionStatus.COMPLETED):self.stage,self.status,self.items=stage,status,{}
    def execute(self,identity,preceding):return (f"{self.stage.value.lower()}:{identity.case_id}","1",preceding)
    def persist(self,artifact):self.items[artifact[0]]=artifact
    def release(self):pass
    def reread(self,reference_id,version):return self.items.get(reference_id)
    def describe(self,artifact):return StageExecution(self.stage,self.status,artifact[0],artifact[1],(f"prov:{self.stage.value.lower()}",),NOW)
def identity():return E2ECaseIdentity("exec-synthetic","case-synthetic","tenant-test","org-test","principal-test","CLINICAL_VALIDATION","corr-test",("policy-v1",),NOW)
def test_reference_only_harness_requires_every_stage_persist_reread_and_complete_trace():
    repository=MemoryManifests();stages=tuple(Stage(x,ExecutionStatus.REVIEW_REQUIRED if x is AcceptanceStage.HUMAN_REVIEW else ExecutionStatus.COMPLETED) for x in AcceptanceStage)
    harness=CanonicalE2EAcceptanceHarness(stages,repository,clock=lambda:NOW);result=harness.run(identity())
    assert result.status is ExecutionStatus.COMPLETED and result.manifest.complete
    assert harness.reconstruct(identity().execution_id)==result.manifest
    assert all(x.reference_id and x.provenance_references for x in result.manifest.stages)
def test_blocked_case_stops_without_fabricating_downstream_trace():
    stages=tuple(Stage(x,ExecutionStatus.BLOCKED if x is AcceptanceStage.REASONING_INPUT else ExecutionStatus.COMPLETED) for x in AcceptanceStage)
    result=CanonicalE2EAcceptanceHarness(stages,MemoryManifests(),clock=lambda:NOW).run(identity())
    assert result.status is ExecutionStatus.BLOCKED and result.manifest.stages[-1].stage is AcceptanceStage.REASONING_INPUT
    assert not result.manifest.complete
def test_approved_order_places_reasoning_input_after_scientific_governance():
    order=tuple(AcceptanceStage)
    assert order.index(AcceptanceStage.TERMINOLOGY)<order.index(AcceptanceStage.REASONING_INPUT)
    assert order.index(AcceptanceStage.EVIDENCE_PACKAGE)<order.index(AcceptanceStage.CLINICAL_APPRAISAL)<order.index(AcceptanceStage.GOVERNED_EVIDENCE)<order.index(AcceptanceStage.REASONING_INPUT)
def test_missing_stage_or_incomplete_handoff_fails_closed():
    with pytest.raises(AcceptanceHarnessError):CanonicalE2EAcceptanceHarness((Stage(AcceptanceStage.INGESTION),),MemoryManifests(),clock=lambda:NOW)
    stages=list(Stage(x) for x in AcceptanceStage);stages[2].describe=lambda artifact:StageExecution(AcceptanceStage.CLINICAL_STATE,ExecutionStatus.COMPLETED,None,None,(),NOW)
    with pytest.raises(AcceptanceHarnessError,match="incomplete"):CanonicalE2EAcceptanceHarness(tuple(stages),MemoryManifests(),clock=lambda:NOW).run(identity())
