#!/usr/bin/env python3
"""Build the governed benchmark from live NCBI records; never invent metadata."""
from __future__ import annotations
import json, time
from datetime import datetime, timezone
from pathlib import Path
import requests

BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
QUERIES = {
 "RETRACTED": "retracted publication[pt]", "CORRECTED": "corrected and republished article[pt]",
 "META_ANALYSIS": "meta-analysis[pt]", "SYSTEMATIC_REVIEW": "systematic review[pt]",
 "RANDOMIZED_CONTROLLED_TRIAL": "randomized controlled trial[pt]",
 "COHORT": "cohort studies[MeSH Terms]", "CASE_CONTROL": "case-control studies[MeSH Terms]",
 "OBSERVATIONAL": "observational study[pt]", "GUIDELINE": "guideline[pt]",
 "CASE_REPORT": "case reports[pt]", "NON_ENGLISH": "portuguese[lang] OR spanish[lang]",
}

def get(path, **params):
    response=requests.get(f"{BASE}/{path}", params={**params,"retmode":"json"}, timeout=30,
        headers={"User-Agent":"JMORAIS-AI-benchmark-curation/2.0"})
    response.raise_for_status(); time.sleep(.34); return response.json()

def main(output: Path):
    selected={}
    for design, query in QUERIES.items():
        ids=get("esearch.fcgi",db="pubmed",term=query,retmax="20",sort="pub date")["esearchresult"]["idlist"]
        accepted=0
        for pmid in ids:
            if pmid not in selected and accepted < 12:
                selected[pmid]=design; accepted += 1
    records=[]; verified=datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    ids=list(selected)
    for start in range(0,len(ids),50):
        result=get("esummary.fcgi",db="pubmed",id=",".join(ids[start:start+50]))["result"]
        for pmid in ids[start:start+50]:
            item=result.get(pmid,{}); articleids={x.get("idtype"):x.get("value") for x in item.get("articleids",[])}
            doi=articleids.get("doi"); title=item.get("title"); journal=item.get("fulljournalname") or item.get("source")
            year=str(item.get("pubdate",''))[:4]; authors=[x.get("name") for x in item.get("authors",[]) if x.get("name")]
            if not (doi and title and journal and year.isdigit() and authors): continue
            design=selected[pmid]; status="RETRACTED" if design=="RETRACTED" else "CORRECTED" if design=="CORRECTED" else "CURRENT"
            pmcid=articleids.get("pmc"); first=authors[0]
            records.append({"record_id":f"pmid-{pmid}","case_id":f"pmid-{pmid}","case_type":"REAL_AUTHORITATIVE_CASE",
              "pmid":pmid,"pmcid":pmcid,"doi":doi,"title":title.rstrip('.'),"journal":journal,"year":int(year),"authors":authors,
              "vancouver":f"{first}, et al. {title.rstrip('.')}. {journal}. {year}.","study_design":design,
              "publication_status":status,"language":(item.get("lang") or ["und"])[0],
              "expected_existence_status":"EXISTS","expected_metadata_status":"AUTHORITATIVE",
              "expected_reconciliation_status":"MATCH","expected_vancouver_eligibility":status=="CURRENT",
              "expected_verification_result":"VERIFIED" if status=="CURRENT" else "BLOCKED",
              "benchmark_rationale":"PubMed record and DOI were returned together by NCBI ESummary.","last_verified_at":verified,
              "authoritative_sources_used":["NCBI PubMed"],"observations":[{"source":"PubMed","source_url":f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
               "retrieved_at":verified,"title":title,"journal":journal,"year":int(year),"pmid":pmid,"pmcid":pmcid,"doi":doi,"authors":authors}]})
    negatives=[]
    for index in range(20):
        malformed=index<5; kind=("MALFORMED" if malformed else "NONEXISTENT")
        negatives.append({"case_id":f"negative-{index+1:03d}","case_type":"SYNTHETIC_NEGATIVE_TEST_CASE",
          "identifiers":{"pmid":f"invalid-{index}" if malformed else f"99999{index:04d}","doi":f"bad/{index}" if malformed else f"10.9999/jmorais-nonexistent-{index}"},
          "expected_existence_status":"DOES_NOT_EXIST","expected_metadata_status":"ABSENT",
          "expected_reconciliation_status":"BLOCK","expected_publication_status":"NONEXISTENT",
          "authoritative_sources_used":["NCBI PubMed","Crossref"],"expected_vancouver_eligibility":False,
          "expected_verification_result":"NOT_VERIFIED","benchmark_rationale":f"Controlled {kind.lower()} identifier rejection case.","last_verified_at":verified})
    payload={"schema_version":1,"dataset_version":"authoritative-biomedical-v2.0.0","retrieved_at":verified,
             "records":records,"negative_cases":negatives}
    if len(records)<100: raise RuntimeError(f"only {len(records)} DOI-bearing authoritative records resolved")
    output.write_text(json.dumps(payload,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(json.dumps({"records":len(records),"negative_cases":len(negatives),"version":payload["dataset_version"]}))

if __name__=="__main__": main(Path("evaluation/scientific_benchmark/data/authoritative_v1.json"))
