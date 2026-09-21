#!/usr/bin/env python3
"""Deterministic PostgreSQL ledger scale measurement; payloads are non-medical."""
from __future__ import annotations
import json, os, resource, statistics, time
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4
from sqlalchemy import create_engine, text
from jmoraIs.evidence_ledger import AppendOnlyEvidenceLedger
from jmoraIs.infrastructure.cryptographic_replay import PostgreSQLCryptographicReplayEngine

def pct(values,p):
    ordered=sorted(values);return ordered[min(round((len(ordered)-1)*p),len(ordered)-1)]
def encode(item):
    data=asdict(item)
    for key,value in tuple(data.items()):
        if isinstance(value,datetime):data[key]=value.isoformat()
    return json.dumps(data,sort_keys=True)

def run(url,profile,events,output):
    engine=create_engine(url,future=True);now=datetime(2026,1,1,tzinfo=timezone.utc)
    claim_id=f"perf-{profile.lower()}-{uuid4().hex}";ledger=AppendOnlyEvidenceLedger()
    ledger.create_claim(f"Synthetic infrastructure stream {profile}",claim_id=claim_id,created_at=now)
    domain_latencies=[]
    for index in range(events):
        started=time.perf_counter();ledger.register_evidence(claim_id=claim_id,source_name="SYNTHETIC_INFRASTRUCTURE",
          source_type="performance",passage=f"non-medical-{profile}-payload-{index}",payload_hash=f"{profile}-{index}".encode().hex()[:64].ljust(64,"0"),
          retrieved_at=now+timedelta(microseconds=index),verification_version="PERF-1",pipeline_version="PERF-1",
          policy_version="PERF-1",support_direction="neutral",source_locator=f"perf:{profile}:{index}",occurred_at=now+timedelta(microseconds=index))
        domain_latencies.append((time.perf_counter()-started)*1000)
    claim=ledger.claims[0];fragments=list(ledger.fragments);supports=list(ledger.supports);event_rows=list(ledger.events)
    with engine.begin() as c:
        c.execute(text("INSERT INTO canonical_ledger_claims(claim_id,payload) VALUES(:id,CAST(:payload AS jsonb))"),{"id":claim_id,"payload":encode(claim)})
        c.execute(text("INSERT INTO canonical_ledger_fragments(fragment_id,payload) VALUES(:id,CAST(:payload AS jsonb))"),
          [{"id":x.fragment_id,"payload":encode(x)} for x in fragments])
        c.execute(text("INSERT INTO canonical_ledger_supports(support_id,claim_id,payload) VALUES(:id,:claim,CAST(:payload AS jsonb))"),
          [{"id":x.support_id,"claim":claim_id,"payload":encode(x)} for x in supports])
    batch_latencies=[];inserted=0;insert_started=time.perf_counter()
    for start in range(0,events,1000):
        batch=event_rows[start:start+1000];began=time.perf_counter()
        with engine.begin() as c:
            c.execute(text("""INSERT INTO canonical_ledger_events(event_id,claim_id,stream_position,previous_event_hash,event_hash,occurred_at,payload)
              VALUES(:id,:claim,:position,:previous,:hash,:occurred,CAST(:payload AS jsonb))"""),
              [{"id":x.event_id,"claim":claim_id,"position":start+i+1,"previous":x.previous_event_hash,
                "hash":x.event_hash,"occurred":x.occurred_at,"payload":encode(x)} for i,x in enumerate(batch)])
        elapsed=time.perf_counter()-began;inserted+=len(batch);batch_latencies.extend([elapsed/len(batch)*1000]*len(batch))
    insert_seconds=time.perf_counter()-insert_started
    replay=PostgreSQLCryptographicReplayEngine(engine);began=time.perf_counter();stream_report=replay.replay_stream("canonical_ledger_events",claim_id);single=time.perf_counter()-began
    began=time.perf_counter();full=replay.replay_all();full_seconds=time.perf_counter()-began
    with engine.connect() as c: size=c.execute(text("SELECT pg_database_size(current_database())")).scalar_one()
    result={"profile":profile,"event_count":events,"stream":claim_id,"integrity":stream_report.integrity_status.value,
      "append_ms":{"p50":pct(batch_latencies,.50),"p95":pct(batch_latencies,.95),"p99":pct(batch_latencies,.99)},
      "append_throughput_events_s":inserted/insert_seconds,"single_stream_replay_seconds":single,
      "single_stream_replay_throughput_events_s":events/single,"full_replay_seconds":full_seconds,
      "full_replay_events":full.verified_events,"full_replay_integrity":full.integrity_status.value,
      "domain_prepare_ms":{"p50":pct(domain_latencies,.5),"p95":pct(domain_latencies,.95),"p99":pct(domain_latencies,.99)},
      "max_rss_kb":resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,"database_size_bytes":size}
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n");print(json.dumps(result,sort_keys=True))
    return 0 if result["integrity"]==result["full_replay_integrity"]=="VALID" else 2

if __name__=="__main__":
    profile=os.getenv("PERFORMANCE_PROFILE","SMALL");profiles={"SMALL":100,"MEDIUM":10000,"LARGE":100000}
    raise SystemExit(run(os.environ["JMORAIS_TEST_POSTGRES_URL"],profile,profiles[profile],Path(os.getenv("PERFORMANCE_REPORT",f"evaluation/performance/{profile.lower()}.json"))))
