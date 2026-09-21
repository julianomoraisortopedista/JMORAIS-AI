#!/usr/bin/env python3
"""Classify every changed worktree path for reproducible release review."""
import json,subprocess
from datetime import datetime,timezone
from pathlib import Path
from jmoraIs import __version__

def classify(path):
    if path.startswith(("UNKNOWN.egg-info/","build/","dist/")) or path.endswith(("coverage.xml",".pyc")): return "GENERATED"
    if "/reports/" in path or path.startswith("evaluation/performance/") or path.startswith("evaluation/release_evidence/"): return "GENERATED"
    if path.startswith((".env",".idea/",".vscode/")) or path.endswith((".db",".sqlite",".dump")): return "LOCAL_ONLY"
    return "INCLUDE"

lines=subprocess.check_output(["git","status","--porcelain=v1","-uall"],text=True).splitlines()
items=[]
for line in lines:
    status=line[:2].strip();path=line[3:]
    items.append({"path":path,"git_status":status,"classification":classify(path)})
result={"generated_at":datetime.now(timezone.utc).isoformat(),"branch":subprocess.check_output(["git","branch","--show-current"],text=True).strip(),
        "candidate_version":__version__,"items":items,
        "counts":{kind:sum(item["classification"]==kind for item in items) for kind in ("INCLUDE","EXCLUDE","GENERATED","LOCAL_ONLY")}}
output=Path("docs/BETA_RELEASE_INVENTORY.json");output.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
print(json.dumps(result["counts"],sort_keys=True))
