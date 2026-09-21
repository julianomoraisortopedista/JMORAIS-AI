import asyncio
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from jmoraIs.api.configuration import RuntimeSecurityPolicy
from jmoraIs.api.runtime_security import RuntimeSecurityMiddleware
from jmoraIs.infrastructure.telemetry import BoundedOpenTelemetryExporter, OpenTelemetrySecurityConfig

ROOT = Path(__file__).resolve().parents[1]


def secured_app(**overrides):
    policy = RuntimeSecurityPolicy(allowed_hosts=("api.internal",), trusted_proxy_cidrs=("10.0.0.0/8",),
        rate_limit_requests=2, rate_limit_window_seconds=60, **overrides)
    app = FastAPI()
    @app.get("/ok")
    async def ok(): return {"ok": True}
    @app.post("/echo")
    async def echo(): return {"ok": True}
    app.add_middleware(RuntimeSecurityMiddleware, policy=policy)
    return app


def test_tls_host_and_proxy_headers_fail_closed():
    api = TestClient(secured_app(), base_url="https://api.internal")
    assert api.get("/ok").status_code == 200
    assert TestClient(secured_app(), base_url="http://api.internal").get("/ok").status_code == 426
    assert TestClient(secured_app(), base_url="https://evil.internal").get("/ok").status_code == 400
    spoofed = api.get("/ok", headers={"x-forwarded-proto": "https", "x-forwarded-for": "10.1.1.1"})
    assert spoofed.status_code == 400 and spoofed.json()["code"] == "UNTRUSTED_PROXY_HEADERS"


def test_plaintext_exception_is_liveness_only_and_loopback_only():
    app = secured_app()
    api = TestClient(app, base_url="http://api.internal", client=("127.0.0.1", 50000))
    assert api.get("/internal/api/v1/health/live").status_code == 404
    assert api.get("/ok").status_code == 426
    remote = TestClient(app, base_url="http://api.internal", client=("192.0.2.5", 50000))
    assert remote.get("/internal/api/v1/health/live").status_code == 426


def test_actual_body_rate_and_security_headers_are_bounded():
    api = TestClient(secured_app(max_request_bytes=8), base_url="https://api.internal")
    too_large = api.post("/echo", content=b"123456789", headers={"transfer-encoding": "chunked"})
    assert too_large.status_code == 413
    first = api.get("/ok"); second = api.get("/ok"); limited = api.get("/ok")
    assert first.status_code == second.status_code == 200 and limited.status_code == 429
    assert limited.headers["retry-after"] and first.headers["cache-control"] == "no-store"
    assert first.headers["x-content-type-options"] == "nosniff"


def test_request_timeout_is_safe_and_bounded():
    app = FastAPI()
    @app.get("/slow")
    async def slow(): await asyncio.sleep(1.05); return {"unsafe": True}
    app.add_middleware(RuntimeSecurityMiddleware, policy=RuntimeSecurityPolicy(
        allowed_hosts=("api.internal",), request_timeout_seconds=1))
    response = TestClient(app, base_url="https://api.internal").get("/slow")
    assert response.status_code == 504 and "traceback" not in response.text.casefold()


class Transport:
    def __init__(self): self.calls = []
    def export(self, endpoint, batch, timeout): self.calls.append((endpoint, batch, timeout))


def test_telemetry_is_allowlisted_bounded_and_payload_free():
    config = OpenTelemetrySecurityConfig("https://otel.internal/v1/metrics", ("otel.internal",),
        timeout_seconds=3, max_buffered_points=1)
    transport = Transport(); exporter = BoundedOpenTelemetryExporter(config, transport)
    exporter.add_counter("requests", 1, {"route": "/internal/api/v1/version", "outcome": "ok"})
    exporter.add_counter("requests", 1, {"route": "/ignored"})
    assert exporter.dropped_points == 1
    exporter.flush(); assert transport.calls[0][2] == 3
    with pytest.raises(ValueError): exporter.add_counter("unsafe", 1, {"jti": "raw-value"})
    with pytest.raises(ValueError): OpenTelemetrySecurityConfig("http://otel.internal", ("otel.internal",))


def test_runtime_boundary_has_no_domain_or_offline_verifier_dependency():
    source = (ROOT / "jmoraIs/api/runtime_security.py").read_text().casefold()
    assert "offline_replay" not in source and "patientcontext" not in source
    assert "from jmoraIs.clinical" not in source and "evidencepackage" not in source
