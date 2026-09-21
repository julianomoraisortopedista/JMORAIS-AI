from __future__ import annotations

from .domain import SmartLaunchContext,SmartLaunchContextRejected


class SmartLaunchContextParser:
    _allowed=frozenset({"patient","encounter","practitioner","organization","user"})
    def parse(self,claims):
        if not isinstance(claims,dict):raise SmartLaunchContextRejected("launch context must be an object")
        unsupported=set(claims)-self._allowed
        if unsupported:raise SmartLaunchContextRejected("unsupported launch context extension")
        if any(value is not None and (not isinstance(value,str) or not value.strip()) for value in claims.values()):
            raise SmartLaunchContextRejected("launch context references must be non-empty strings")
        return SmartLaunchContext(claims.get("patient"),claims.get("encounter"),claims.get("practitioner"),
            claims.get("organization"),claims.get("user"))
