#!/usr/bin/env python3
"""Persist Crossref/OpenAlex reconciliation and governed real conflict cases."""
from __future__ import annotations
import json, os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from evaluation.scientific_benchmark.sources import AuthoritativeClients
from evaluation.scientific_benchmark.validation import normalize_doi, normalize_text

DATA=Path("evaluation/scientific_benchmark/data/authoritative_v1.json")

def main():
    payload=json.loads(DATA.read_text()); clients=AuthoritativeClients(timeout=15)
    now=datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    def fetch(task):
        record,source=task
        try: return record["record_id"],source,getattr(clients,source)(record["doi"]),None
        except Exception as exc: return record["record_id"],source,None,type(exc).__name__
    tasks=[(record,source) for record in payload["records"] for source in ("crossref","openalex")]
    results={}
    with ThreadPoolExecutor(max_workers=int(os.getenv("BENCHMARK_WORKERS","4"))) as pool:
        for rid,source,data,error in pool.map(fetch,tasks): results[(rid,source)]=(data,error)
    conflicts=[]
    for record in payload["records"]:
        record["observations"]=[item for item in record["observations"] if item["source"]=="PubMed"]
        sources={"PubMed"}; unavailable=[];record_conflict_fields=set()
        for source,label in (("crossref","Crossref"),("openalex","OpenAlex")):
            data,error=results[(record["record_id"],source)]
            if data is None: unavailable.append({"source":label,"reason":error});continue
            if source=="crossref":
                title=(data.get("title") or [None])[0]; journal=(data.get("container-title") or [None])[0]
                parts=(data.get("published") or data.get("issued") or {}).get("date-parts") or [[]]
                year=parts[0][0] if parts and parts[0] else None; doi=data.get("DOI")
            else:
                title=data.get("title"); journal=(data.get("primary_location") or {}).get("source",{}).get("display_name")
                year=data.get("publication_year"); doi=data.get("doi")
            record["observations"].append({"source":label,"source_url":f"https://api.{source}.org/works/{record['doi']}",
              "retrieved_at":now,"title":title,"journal":journal,"year":year,"pmid":record["pmid"],"pmcid":record.get("pmcid"),"doi":doi})
            sources.add(label)
            differences=[]
            if title and normalize_text(title)!=normalize_text(record["title"]): differences.append("TITLE")
            if year and int(year)!=record["year"]: differences.append("YEAR")
            if doi and normalize_doi(doi)!=normalize_doi(record["doi"]): differences.append("DOI")
            if differences:
                record_conflict_fields.update(differences)
                conflicts.append({"case_id":f"conflict-{record['record_id']}-{source}","case_type":"REAL_AUTHORITATIVE_CONFLICT_CASE",
                  "identifiers":{"pmid":record["pmid"],"doi":record["doi"]},"conflict_type":"METADATA_MISMATCH",
                  "conflicting_source":label,"fields":differences,"expected_resolution":"BLOCK_VERIFIED_AND_REQUIRE_RECONCILIATION",
                  "authoritative_sources_used":["PubMed",label],"benchmark_rationale":"Persisted live authoritative metadata differs from the PubMed baseline.","last_verified_at":now})
        record["authoritative_sources_used"]=sorted(sources);record["source_unavailability"]=unavailable
        record["last_verified_at"]=now
        if {"TITLE","DOI"}.intersection(record_conflict_fields):
            record["expected_reconciliation_status"]="CONFLICT"
            record["expected_verification_result"]="CONFLICTING_METADATA"
            record["expected_vancouver_eligibility"]=False
        elif record["publication_status"]=="CURRENT":
            record["expected_reconciliation_status"]="MATCH"
            record["expected_verification_result"]="VERIFIED"
        if record["publication_status"] in {"CORRECTED","RETRACTED"}:
            conflicts.append({"case_id":f"editorial-{record['record_id']}","case_type":"REAL_AUTHORITATIVE_CONFLICT_CASE",
              "identifiers":{"pmid":record["pmid"],"doi":record["doi"]},"conflict_type":record["publication_status"],
              "conflicting_source":"PubMed","fields":["PUBLICATION_STATUS"],
              "expected_resolution":"BLOCK" if record["publication_status"]=="RETRACTED" else "REVERIFY_CORRECTED_VERSION",
              "authoritative_sources_used":["PubMed"],"benchmark_rationale":"Authoritative PubMed publication type requires governed handling.","last_verified_at":now})
    payload["conflict_cases"]=conflicts;payload["reconciliation_persisted_at"]=now
    DATA.write_text(json.dumps(payload,indent=2,ensure_ascii=False)+"\n")
    eligible=[r for r in payload["records"] if r["publication_status"]=="CURRENT"]
    summary={"records":len(payload["records"]),"eligible":len(eligible),"three_sources":sum(len(r["authoritative_sources_used"])>=3 for r in eligible),
             "documented_unavailability":sum(bool(r["source_unavailability"]) for r in eligible),"conflicts":len(conflicts)}
    print(json.dumps(summary,sort_keys=True));return 0 if summary["conflicts"]>=15 else 2

if __name__=="__main__": raise SystemExit(main())
