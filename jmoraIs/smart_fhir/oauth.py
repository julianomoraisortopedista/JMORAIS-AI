from __future__ import annotations

import base64,hashlib,re
from .domain import SmartPkceRejected


_VERIFIER=re.compile(r"[A-Za-z0-9._~-]{43,128}")


class SmartPkceS256:
    @staticmethod
    def challenge(verifier):
        if not isinstance(verifier,str) or not _VERIFIER.fullmatch(verifier):raise SmartPkceRejected("invalid PKCE verifier")
        return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
    def verify(self,verifier,challenge,method="S256"):
        if method!="S256":raise SmartPkceRejected("only PKCE S256 is allowed")
        if not isinstance(challenge,str) or not challenge:raise SmartPkceRejected("PKCE challenge is required")
        if not __import__("hmac").compare_digest(self.challenge(verifier),challenge):raise SmartPkceRejected("PKCE verification failed")
        return True
