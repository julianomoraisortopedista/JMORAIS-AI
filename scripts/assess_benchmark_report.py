#!/usr/bin/env python3
"""Re-evaluate retained source observations against immutable beta thresholds."""
import json, sys
from pathlib import Path

def main(source: Path, output: Path) -> int:
    report=json.loads(source.read_text()); sources=report["sources"]
    authoritative=[v for k,v in sources.items() if k!="semantic_scholar"]
    attempted=sum(v["attempted"] for v in authoritative); resolved=sum(v["resolved"] for v in authoritative)
    resolution=resolved/max(attempted,1)
    checks={"dataset_size":report["dataset_size"]>=100,"precision":report["precision"]>=.98,
      "recall":report["recall"]>=.95,"false_positive_rate":report["false_positive_rate"]<=.01,
      "false_negative_rate":report["false_negative_rate"]<=.05,"identifier_resolution":resolution>=.90,
      "reconciliation":resolution>=.90,
      "authoritative_source_availability":all(v["failure_rate"]<=.20 for v in authoritative)}
    result={"source_report":str(source),"authoritative_resolution":resolution,"checks":checks,
            "semantic_scholar_supplementary_failure_rate":sources["semantic_scholar"]["failure_rate"],
            "decision":"PASS" if all(checks.values()) else "FAIL"}
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    print(json.dumps(result,sort_keys=True));return 0 if result["decision"]=="PASS" else 2

if __name__=="__main__": raise SystemExit(main(Path(sys.argv[1]),Path(sys.argv[2])))
