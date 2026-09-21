from __future__ import annotations

import json
import jwt

from .domain import SmartConfigurationRejected,SmartJwk,SmartTokenRejected


class StaticSmartJwks:
    """Immutable deterministic JWKS set; fetching and rotation remain transport concerns."""
    def __init__(self,keys):self._keys={item.key_id:item for item in keys}
    @classmethod
    def parse(cls,payload:bytes,*,allowed_algorithms=("RS256",)):
        try:value=json.loads(payload.decode("utf-8"))
        except (AttributeError,UnicodeDecodeError,json.JSONDecodeError) as exc:raise SmartConfigurationRejected("invalid JWKS JSON") from exc
        values=value.get("keys",()) if isinstance(value,dict) else ()
        parsed=[];seen=set()
        for item in values:
            kid=item.get("kid");alg=item.get("alg");kty=item.get("kty");use=item.get("use","sig")
            if not kid or kid in seen:raise SmartConfigurationRejected("JWKS key identifiers must be unique")
            if alg not in allowed_algorithms or alg.lower()=="none" or kty not in {"RSA","EC"} or use!="sig":
                raise SmartConfigurationRejected("JWKS signing key policy rejected")
            try:key=jwt.PyJWK.from_dict(item).key
            except Exception as exc:raise SmartConfigurationRejected("invalid JWKS signing key") from exc
            parsed.append(SmartJwk(kid,alg,kty,use,key));seen.add(kid)
        if not parsed:raise SmartConfigurationRejected("JWKS contains no trusted signing keys")
        return cls(tuple(parsed))
    def resolve(self,key_id,algorithm):
        value=self._keys.get(key_id)
        if value is None or value.algorithm!=algorithm:raise SmartTokenRejected("signing key cannot be established")
        return value
