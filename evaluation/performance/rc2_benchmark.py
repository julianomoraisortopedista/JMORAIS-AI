from __future__ import annotations

import gc
import asyncio
import hashlib
import hmac
import json
import os
import platform
import resource
import statistics
import time
import tracemalloc
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy import create_engine, text

from jmoraIs import __version__
from jmoraIs.api.app import ApiOperationalServices, ApiServices, create_app
from jmoraIs.api.configuration import RuntimeSecurityPolicy
from jmoraIs.api.identity_security import CanonicalApiAuthorizationPolicy
from jmoraIs.api.security import CallerRole, PurposeOfUse, ReadinessCheck
from jmoraIs.api.security_infrastructure import (DeterministicDevelopmentAuthenticator,
    DevelopmentIdentity, StaticReadinessProbe)
from jmoraIs.infrastructure.production_runtime import CURRENT_SCHEMA_REVISION


def percentiles(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    def pick(fraction: float) -> float:
        return ordered[min(round((len(ordered) - 1) * fraction), len(ordered) - 1)]
    return {"p50": pick(.50), "p90": pick(.90), "p95": pick(.95),
            "p99": pick(.99), "max": ordered[-1]}


def _memory_bytes() -> int | None:
    try: return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (ValueError, OSError, AttributeError): return None


@dataclass(frozen=True)
class BenchmarkEnvironment:
    measured_at: str
    application_version: str
    source_revision: str
    build_id: str
    python_version: str
    postgresql_version: str
    alembic_revision: str
    operating_system: str
    machine: str
    cpu_count: int | None
    memory_bytes: int | None
    container_limits: str
    worker_configuration: str
    pool_configuration: str
    dataset_bytes: int
    tenant_count: int


class _NonRetainingSink:
    def append(self, _value) -> None: pass
    def observe(self, _value) -> None: pass
    def emit(self, _value) -> None: pass


async def _api_measure(app, request_headers, samples):
    ladder = {}; memory_cycles = []
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="https://api.internal",
                                 headers=request_headers) as client:
        async def once(semaphore):
            async with semaphore:
                started = time.perf_counter_ns()
                response = await client.get("/internal/api/v1/version")
                return (time.perf_counter_ns() - started) / 1_000_000, response.status_code
        await once(asyncio.Semaphore(1))
        for concurrency in (1, 2, 4, 8, 16, 32):
            semaphore = asyncio.Semaphore(concurrency); started = time.perf_counter()
            values = await asyncio.gather(*(once(semaphore) for _ in range(samples)))
            elapsed = time.perf_counter() - started; latencies = [item[0] for item in values]
            ladder[str(concurrency)] = {"latency_ms": percentiles(latencies),
                "requests_per_second": samples / elapsed,
                "success_rate": sum(status == 200 for _, status in values) / samples,
                "requests": samples}
        tracemalloc.start()
        for _ in range(5):
            semaphore = asyncio.Semaphore(16)
            await asyncio.gather(*(once(semaphore) for _ in range(200)))
            gc.collect(); current, peak = tracemalloc.get_traced_memory()
            memory_cycles.append({"current_bytes": current, "peak_bytes": peak})
            tracemalloc.reset_peak()
        tracemalloc.stop()
    return ladder, memory_cycles


def run(url: str, output: Path, *, samples: int = 500) -> dict:
    cpu_started = time.process_time()
    engine = create_engine(url, future=True, pool_size=10, max_overflow=5,
                           pool_timeout=10, pool_pre_ping=True)
    with engine.connect() as connection:
        pg_version = connection.execute(text("SHOW server_version")).scalar_one()
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        database_size = connection.execute(text("SELECT pg_database_size(current_database())")).scalar_one()
        tenant_count = connection.execute(text("SELECT count(*) FROM tenants")).scalar_one()
    environment = BenchmarkEnvironment(datetime.now(timezone.utc).isoformat(), __version__,
        os.getenv("JMORAIS_SOURCE_REVISION", "UNCOMMITTED_WORKTREE"),
        os.getenv("JMORAIS_BUILD_ID", "rc2-local-validation"), platform.python_version(),
        pg_version, revision, platform.platform(), platform.machine(), os.cpu_count(), _memory_bytes(),
        os.getenv("JMORAIS_CONTAINER_LIMITS", "host process; no cgroup limit applied"),
        "benchmark in-process; production image default=2 workers/100 concurrency",
        "reader/writer pool_size=10 max_overflow=5; verifier=1/0", database_size, tenant_count)

    policy = RuntimeSecurityPolicy(allowed_hosts=("api.internal",), rate_limit_requests=1_000_000,
                                   rate_limit_window_seconds=3600)
    token = "rc2-local-benchmark-token-0000000001"
    authentication = DeterministicDevelopmentAuthenticator((DevelopmentIdentity.from_token(
        "rc2-benchmark", CallerRole.INTERNAL_SERVICE, token,
        (PurposeOfUse.INTERNAL_OPERATIONS,), "api-access-v1"),))
    operations = ApiOperationalServices(authentication, CanonicalApiAuthorizationPolicy(),
        StaticReadinessProbe((ReadinessCheck("benchmark", True, "AVAILABLE"),)),
        _NonRetainingSink(), _NonRetainingSink(), _NonRetainingSink())
    app = create_app(ApiServices(), operations, runtime_security=policy)
    api_ladder, memory_cycles = asyncio.run(_api_measure(app, {"authorization": f"Bearer {token}",
        "x-purpose": "INTERNAL_OPERATIONS"}, samples))

    pg_latencies = []
    for _ in range(samples):
        started = time.perf_counter_ns()
        with engine.connect() as connection: connection.execute(text("SELECT 1")).scalar_one()
        pg_latencies.append((time.perf_counter_ns() - started) / 1_000_000)

    payload = b"rc2-deterministic-non-medical-payload" * 8
    crypto = []
    for _ in range(samples * 20):
        started = time.perf_counter_ns()
        digest = hashlib.sha256(payload).digest()
        hmac.new(b"rc2-benchmark-key-material-32bytes", digest, hashlib.sha256).digest()
        crypto.append((time.perf_counter_ns() - started) / 1_000_000)

    plans = {}
    with engine.connect() as connection:
        for table, column in (("medical_document_versions", "version_id"),
                              ("audit_defense_versions", "package_id"),
                              ("llm_invocations", "invocation_id"),
                              ("clinical_reasoning_input_versions", "input_id")):
            plan = connection.execute(text(
                f"EXPLAIN (FORMAT JSON) SELECT * FROM {table} WHERE {column}=:value"),
                {"value": "rc2-absent"}).scalar_one()
            plans[table] = plan[0]["Plan"]

    growth = memory_cycles[-1]["current_bytes"] - memory_cycles[0]["current_bytes"]

    result = {"schema_version": 1, "environment": asdict(environment),
        "workloads": {
            "lightweight_authenticated_api": api_ladder,
            "postgresql_round_trip": {"latency_ms": percentiles(pg_latencies),
                "transactions_per_second": 1000 / statistics.mean(pg_latencies)},
            "sha256_hmac": {"latency_ms": percentiles(crypto),
                "operations_per_second": 1000 / statistics.mean(crypto)},
        },
        "query_plans": plans,
        "memory": {"cycles": memory_cycles, "retained_growth_bytes": growth,
            "max_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss},
        "cpu": {"process_seconds": time.process_time() - cpu_started},
        "limits": {"samples_per_api_concurrency": samples, "synthetic_data_only": True,
            "external_provider_latency_included": False,
            "clinical_workload_latency_source": "canonical regression scenario wall times, reported separately"}}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    engine.dispose()
    return result


if __name__ == "__main__":
    report = run(os.environ["JMORAIS_TEST_POSTGRES_URL"],
        Path(os.getenv("RC2_PERFORMANCE_REPORT", "evaluation/performance/rc2-baseline.json")),
        samples=int(os.getenv("RC2_SAMPLES", "500")))
    print(json.dumps(report, sort_keys=True))
