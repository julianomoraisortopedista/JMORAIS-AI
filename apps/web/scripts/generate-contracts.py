"""Generate browser types from the approved Pydantic API models; no invented fields.

Run from repository root with .venv/bin/python apps/web/scripts/generate-contracts.py.
"""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[3]))
from jmoraIs.api import workspace_schemas as schemas
from jmoraIs.api.workspace_launch import WorkspaceBootstrapRequest, WorkspaceBootstrapResponse
models = [WorkspaceBootstrapRequest,WorkspaceBootstrapResponse] + [getattr(schemas,n) for n in (
    'ClinicalSummaryResponse','TimelineResponse','EvidenceResponse','ExplainabilityResponse',
    'MedicalDocumentResponse','HumanReviewResponse','AuditDefenseResponse','WorkspaceContextResponse')]
def convert(s):
    if '$ref' in s: return s['$ref'].rsplit('/',1)[-1]
    if 'anyOf' in s: return ' | '.join(convert(x) for x in s['anyOf'])
    if 'const' in s: return __import__('json').dumps(s['const'])
    if 'enum' in s: return ' | '.join(__import__('json').dumps(x) for x in s['enum'])
    kind=s.get('type')
    if kind=='array': return 'ReadonlyArray<'+convert(s['items'])+'>'
    if kind=='object':
        required=s.get('required',[])
        return '{ '+ '; '.join(k+('' if k in required else '?')+': '+convert(v) for k,v in s.get('properties',{}).items())+' }'
    return {'string':'string','integer':'number','number':'number','boolean':'boolean','null':'null'}.get(kind,'unknown')
definitions={}
for m in models:
    schema=m.model_json_schema();definitions.update(schema.pop('$defs',{}));definitions[m.__name__]=schema
lines=['// Generated from S004/S005 API schemas. Do not edit by hand.']
for name,schema in definitions.items(): lines.append('export type '+name+' = '+convert(schema)+';')
Path('apps/web/src/contracts.d.ts').write_text('\n'.join(lines)+'\n')
