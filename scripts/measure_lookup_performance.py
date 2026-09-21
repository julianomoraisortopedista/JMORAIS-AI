#!/usr/bin/env python3
import json,os,time
from pathlib import Path
from sqlalchemy import create_engine,text
from jmoraIs.infrastructure.postgresql_package_catalog import PostgreSQLPackageCatalogRepository
from jmoraIs.appraisal.persistence import SQLAlchemyGovernedEvidenceRepository
from jmoraIs.clinical.governance_persistence import SQLAlchemyGovernedEvidenceLifecycleRepository
from evaluation.scientific_benchmark.dataset import BenchmarkDatasetLoader
from evaluation.scientific_benchmark.runner import BenchmarkRunner

def stats(values):
    values=sorted(values);at=lambda p:values[min(round((len(values)-1)*p),len(values)-1)]
    return {"p50":at(.5),"p95":at(.95),"p99":at(.99)}
def sample(fn,n=1000):
    values=[]
    for _ in range(n): started=time.perf_counter();fn();values.append((time.perf_counter()-started)*1000)
    return stats(values)

engine=create_engine(os.environ["JMORAIS_TEST_POSTGRES_URL"],future=True)
with engine.connect() as c:
    package=c.execute(text("SELECT package_id FROM evidence_package_catalog LIMIT 1")).scalar_one()
    governed=c.execute(text("SELECT governed_evidence_id FROM governed_evidence_versions LIMIT 1")).scalar_one()
packages=PostgreSQLPackageCatalogRepository(engine);evidence=SQLAlchemyGovernedEvidenceRepository(engine);lifecycle=SQLAlchemyGovernedEvidenceLifecycleRepository(engine)
version,records=BenchmarkDatasetLoader().load();thousand=tuple(records[index%len(records)] for index in range(1000))
result={"package_lookup_ms":sample(lambda:packages.get(package)),"governed_evidence_lookup_ms":sample(lambda:evidence.get(governed)),
 "lifecycle_lookup_ms":sample(lambda:lifecycle.history(governed))}
started=time.perf_counter();BenchmarkRunner().run(version,thousand);result["benchmark_normalization_1000_seconds"]=time.perf_counter()-started
path=Path("evaluation/performance/lookups.json");path.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n");print(json.dumps(result,sort_keys=True))
