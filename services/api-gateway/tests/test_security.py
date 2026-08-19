"""Phase 9.1 OWASP hardening tests (security marker).

Covers the web-hardening controls added in 9.1:
  * OWASP security response headers (present; HSTS production-only)
  * request body size limit -> 413 (Content-Length fast path + chunked stream)
  * login brute-force throttling (per-IP bucket -> 429)
  * CORS: no credentials with a wildcard origin; method/header allow-list
"""

from __future__ import annotations

import asyncio

import pytest
from at_shared.http_security import RequestSizeLimitMiddleware, security_headers

HEALTHY_HEADERS = {
    "X-Content-Type-Options",
    "X-Frame-Options",
    "Referrer-Policy",
    "Cross-Origin-Opener-Policy",
    "Permissions-Policy",
    "Content-Security-Policy",
    "Cache-Control",
    "X-XSS-Protection",
}


@pytest.mark.security
def test_security_headers_present_on_all_responses(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    for header in HEALTHY_HEADERS:
        assert header in resp.headers, f"missing {header}"
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert resp.headers["Cache-Control"] == "no-store"
    assert resp.headers["Content-Security-Policy"] == "default-src 'none'"
    # HSTS is production-only (dev/test must not force HTTPS)
    assert "Strict-Transport-Security" not in resp.headers


@pytest.mark.security
def test_security_headers_apply_to_data_endpoints(client):
    resp = client.post(
        "/v1/transactions/screen",
        headers={"X-API-Key": "does-not-matter-for-this-check"},
        json={
            "agent_id": "x",
            "chain_id": "base",
            "from_address": "0x" + "1" * 40,
            "value_wei": 1,
        },
    )
    # 401 (unknown key) is fine — the point is every response carries headers
    assert resp.status_code in (200, 401)
    assert resp.headers["Cache-Control"] == "no-store"


@pytest.mark.security
def test_hsts_only_in_production():
    assert "Strict-Transport-Security" not in security_headers(is_production=False)
    prod = security_headers(is_production=True)
    assert prod["Strict-Transport-Security"].startswith("max-age=31536000")


@pytest.mark.security
def test_oversized_body_rejected_413(client):
    blob = b"x" * 70_000  # > 64 KiB default cap
    resp = client.post(
        "/v1/transactions/screen",
        headers={"X-API-Key": "k", "Content-Type": "application/json"},
        content=blob,
    )
    assert resp.status_code == 413
    assert resp.json()["code"] == "payload_too_large"


@pytest.mark.security
def test_chunked_body_over_cap_413_without_content_length():
    """The streaming path (no Content-Length) must also 413 on overflow."""
    cap = 10_000
    sent: list[dict] = []

    async def app(scope, receive, send):
        # consumer drains the request body until the stream ends
        while True:
            msg = await receive()
            if not msg.get("more_body"):
                return

    async def send(message):
        sent.append(message)

    async def receive():
        # 3 x 6 KiB chunks, streamed with no declared Content-Length
        messages = [
            {"type": "http.request", "body": b"z" * 6144, "more_body": True},
            {"type": "http.request", "body": b"z" * 6144, "more_body": True},
            {"type": "http.request", "body": b"z" * 6144, "more_body": False},
        ]
        for msg in messages:
            yield msg
        yield {"type": "http.request", "body": b"", "more_body": False}

    async def run():
        scope = {"type": "http", "headers": []}
        mw = RequestSizeLimitMiddleware(app, max_body_bytes=cap)

        stream = receive()

        async def next_message():
            return await stream.__anext__()

        await mw(scope, next_message, send)

    asyncio.run(run())

    assert sent, "expected a response"
    assert sent[0]["type"] == "http.response.start"
    assert sent[0]["status"] == 413


@pytest.mark.security
def test_login_brute_force_throttled(client, monkeypatch):
    from app import rate_limit

    monkeypatch.setattr(rate_limit, "LOGIN_BUCKET_CAPACITY", 3)
    monkeypatch.setattr(rate_limit, "LOGIN_REFILL_PER_SEC", 1 / 3600)  # ~no refill within the test

    # a dedicated IP for this test so it never perturbs the shared bucket
    headers = {"X-Forwarded-For": "203.0.113.9"}

    statuses = []
    for _ in range(4):
        resp = client.post(
            "/v1/auth/login",
            headers=headers,
            json={"email": "nobody@agentthreshold.dev", "password": "WrongPass123!"},
        )
        statuses.append(resp.status_code)

    assert statuses[:3] == [401, 401, 401]  # valid auth processing
    assert statuses[3] == 429  # brute force throttled

    throttled = client.post(
        "/v1/auth/login",
        headers=headers,
        json={"email": "nobody@agentthreshold.dev", "password": "WrongPass123!"},
    )
    assert throttled.status_code == 429
    assert "Retry-After" in throttled.headers


@pytest.mark.security
def test_cors_no_credentials_with_wildcard(client):
    # dev default is `*`; preflight must NOT grant credentials with it
    resp = client.options(
        "/v1/transactions/screen",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-api-key",
        },
    )
    assert resp.status_code == 200
    allow_origin = resp.headers.get("access-control-allow-origin")
    assert allow_origin is not None
    assert allow_origin == "*"
    assert resp.headers.get("access-control-allow-credentials", "false") == "false"
    allowed_methods = resp.headers.get("access-control-allow-methods", "")
    assert "GET" in allowed_methods and "POST" in allowed_methods
    assert "DELETE" in allowed_methods
    assert "TRACE" not in allowed_methods  # no dangerous methods allowed
