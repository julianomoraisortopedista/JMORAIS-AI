from __future__ import annotations

import re
from .domain import SmartScope,SmartScopeContext,SmartScopeRejected


_IDENTITY=frozenset({"openid","fhirUser","profile","offline_access"})
_RESOURCE=re.compile(r"patient/([A-Za-z][A-Za-z0-9]*|\*)\.read")


class SmartScopeParser:
    def parse(self,value):
        if not isinstance(value,str) or not value.strip():raise SmartScopeRejected("SMART scopes are required")
        output=[]
        for raw in value.split():
            if raw in _IDENTITY:output.append(SmartScope(raw,SmartScopeContext.IDENTITY,None,raw));continue
            if raw in {"launch","launch/patient"}:output.append(SmartScope(raw,SmartScopeContext.LAUNCH,None,raw));continue
            match=_RESOURCE.fullmatch(raw)
            if match:output.append(SmartScope(raw,SmartScopeContext.PATIENT,match.group(1),"read"));continue
            raise SmartScopeRejected("unsupported or write-capable SMART scope")
        if len({item.raw for item in output})!=len(output):raise SmartScopeRejected("duplicate SMART scope")
        return tuple(output)
