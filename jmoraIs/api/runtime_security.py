from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from dataclasses import dataclass
from hashlib import sha256
from ipaddress import ip_address, ip_network
from time import monotonic
from typing import Awaitable, Callable

from starlette.datastructures import Headers
from starlette.responses import JSONResponse


_FORWARDED = ("forwarded", "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto")


class RuntimeSecurityRejected(RuntimeError):
    pass


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    retry_after_seconds: int = 0


class FixedWindowRateLimiter:
    """Bounded local admission control; distributed ingress limits remain mandatory."""

    def __init__(self, *, requests: int, window_seconds: int, max_keys: int = 10_000) -> None:
        if min(requests, window_seconds, max_keys) < 1:
            raise ValueError("bounded rate-limit policy is required")
        self._requests, self._window, self._max_keys = requests, window_seconds, max_keys
        self._events: dict[str, deque[float]] = defaultdict(deque)

    def admit(self, key: str) -> RateLimitDecision:
        now = monotonic()
        if key not in self._events and len(self._events) >= self._max_keys:
            return RateLimitDecision(False, self._window)
        events = self._events[key]
        while events and now - events[0] >= self._window:
            events.popleft()
        if len(events) >= self._requests:
            return RateLimitDecision(False, max(1, int(self._window - (now - events[0]))))
        events.append(now)
        return RateLimitDecision(True)


class RuntimeSecurityMiddleware:
    """Production HTTP admission boundary with no clinical/domain dependencies."""

    def __init__(self, app, policy) -> None:
        self.app, self.policy = app, policy
        self._semaphore = asyncio.Semaphore(policy.concurrency_limit)
        self._trusted_proxies = tuple(ip_network(value, strict=False) for value in policy.trusted_proxy_cidrs)
        self._limiter = FixedWindowRateLimiter(requests=policy.rate_limit_requests,
            window_seconds=policy.rate_limit_window_seconds)

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send); return
        headers = Headers(scope=scope)
        correlation = headers.get("x-correlation-id", "")[:128]
        error = self._validate_transport(scope, headers)
        if error is not None:
            await self._reject(scope, receive, send, error, correlation); return
        credential = headers.get("authorization", "")
        identity_key = sha256(credential.encode()).hexdigest() if credential else "anonymous"
        decision = self._limiter.admit(f"{identity_key}|{scope.get('path', '')}")
        if not decision.allowed:
            await self._reject(scope, receive, send, (429, "RATE_LIMITED"), correlation,
                               retry_after=decision.retry_after_seconds); return
        body = bytearray(); more = True
        while more:
            message = await receive()
            if message["type"] == "http.disconnect": return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > self.policy.max_request_bytes:
                await self._reject(scope, receive, send, (413, "REQUEST_TOO_LARGE"), correlation); return
            body.extend(chunk); more = message.get("more_body", False)
        delivered = False
        async def bounded_receive():
            nonlocal delivered
            if delivered: return {"type": "http.request", "body": b"", "more_body": False}
            delivered = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}
        async def secure_send(message):
            if message["type"] == "http.response.start":
                values = list(message.get("headers", ()))
                values.extend(((b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"DENY"), (b"referrer-policy", b"no-referrer"),
                    (b"cache-control", b"no-store")))
                message["headers"] = values
            await send(message)
        try:
            await asyncio.wait_for(self._run_bounded(scope, bounded_receive, secure_send),
                                   timeout=self.policy.request_timeout_seconds)
        except asyncio.TimeoutError:
            await self._reject(scope, bounded_receive, send, (504, "REQUEST_TIMEOUT"), correlation)

    async def _run_bounded(self, scope, receive, send):
        async with self._semaphore:
            await self.app(scope, receive, send)

    def _validate_transport(self, scope, headers: Headers):
        host = headers.get("host", "").split(":", 1)[0].lower()
        if host not in self.policy.allowed_hosts:
            return 400, "HOST_REJECTED"
        supplied = any(headers.get(name) is not None for name in _FORWARDED)
        client = (scope.get("client") or ("", 0))[0]
        trusted = False
        try: trusted = any(ip_address(client) in network for network in self._trusted_proxies)
        except ValueError: pass
        if supplied and not trusted:
            return 400, "UNTRUSTED_PROXY_HEADERS"
        scheme = headers.get("x-forwarded-proto") if trusted else scope.get("scheme")
        loopback_health = (scope.get("path") == "/internal/api/v1/health/live"
                           and client in {"127.0.0.1", "::1"} and not supplied)
        if self.policy.tls_termination_required and scheme != "https" and not loopback_health:
            return 426, "TLS_REQUIRED"
        return None

    @staticmethod
    async def _reject(scope, receive, send, failure, correlation, retry_after=0):
        status, code = failure
        headers = {"cache-control": "no-store", "x-content-type-options": "nosniff"}
        if retry_after: headers["retry-after"] = str(retry_after)
        response = JSONResponse({"code": code, "message": "request rejected by runtime security policy",
                                 "correlation_id": correlation or "unavailable"}, status_code=status,
            headers=headers)
        await response(scope, receive, send)
