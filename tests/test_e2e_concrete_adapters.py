from datetime import datetime, timezone

import pytest

from evaluation.e2e_acceptance import *


NOW = datetime(2026, 8, 10, tzinfo=timezone.utc)


class CanonicalService:
    def __init__(self, stage):
        self.stage = stage
        self.calls = 0

    def execute(self, identity, preceding):
        self.calls += 1
        return (f"{self.stage.value}:{identity.case_id}", "1", preceding)


class CanonicalRepository:
    def __init__(self):
        self.items = {}

    def append(self, artifact):
        if artifact[0] in self.items:
            raise RuntimeError("append-only")
        self.items[artifact[0]] = artifact

    def get(self, reference_id, version):
        item = self.items.get(reference_id)
        return item if item and item[1] == version else None


def identity():
    return E2ECaseIdentity(
        "complete-case-execution", "complete-case", "tenant-test", "org-test",
        "reviewer-principal", "CLINICAL_VALIDATION", "corr-complete", ("policy-v1",), NOW,
    )


def test_all_fourteen_concrete_adapters_execute_persist_release_and_reread_once():
    services = []
    adapters = []
    for adapter_type in CANONICAL_ADAPTER_TYPES:
        service = CanonicalService(adapter_type.stage)
        repository = CanonicalRepository()
        services.append(service)
        adapters.append(adapter_type(CanonicalStageBinding(
            service.execute,
            repository.append,
            repository.get,
            lambda artifact, stage=adapter_type.stage: StageExecution(
                stage, ExecutionStatus.REVIEW_REQUIRED if stage is AcceptanceStage.HUMAN_REVIEW else ExecutionStatus.COMPLETED,
                artifact[0], artifact[1], (f"provenance:{stage.value}",), NOW,
            ),
        )))

    manifests = CanonicalRepository()
    manifests.append = lambda value: manifests.items.__setitem__(value.execution_id, value)
    manifests.get = lambda reference_id: manifests.items.get(reference_id)
    result = CanonicalE2EAcceptanceHarness(tuple(adapters), manifests, clock=lambda: NOW).run(identity())

    assert result.manifest.complete
    assert len(result.manifest.stages) == 14
    assert all(service.calls == 1 for service in services)
    assert result.manifest.stages[-1].status is ExecutionStatus.REVIEW_REQUIRED


def test_adapter_requires_release_before_query_port_reread():
    service = CanonicalService(AcceptanceStage.INGESTION)
    repository = CanonicalRepository()
    adapter = AuthorizedClinicalIngestionAdapter(CanonicalStageBinding(
        service.execute, repository.append, repository.get,
        lambda artifact: StageExecution(AcceptanceStage.INGESTION, ExecutionStatus.COMPLETED,
                                        artifact[0], artifact[1], ("provenance",), NOW),
    ))
    artifact = adapter.execute(identity(), None)
    adapter.persist(artifact)
    with pytest.raises(E2EAdapterConfigurationError, match="released"):
        adapter.reread(artifact[0], artifact[1])
