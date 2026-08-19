"""OWASP-friendly HTTP hardening shared by every service (Phase 9.1).

Stdlib-only on purpose: `at_shared` stays framework-agnostic. Each FastAPI app
installs these via `install_http_security(app, ...)`:

  * `security_headers()`       — a consistent set of response headers:
    - X-Content-Type-Options: nosniff
    - X-Frame-Options: DENY (no framing of API responses)
    - Referrer-Policy: strict-origin-when-cross-origin
    - Cross-Origin-Opener-Policy: same-origin
    - Permissions-Policy: no sensitive browser features
    - Content-Security-Policy: default-src 'none' (JSON API has no inline UI)
    - Cache-Control: no-store (never cache auth-bearing responses)
    - X-XSS-Protection: 0 (opt out of the legacy, unreliable reflection filter)
    - Strict-Transport-Security (production only, includeSubDomains)

  * `RequestSizeLimitMiddleware` — rejects request bodies larger than
    `max_body_bytes` with 413 (OWASP A05/A08: limit request size, DoS). The
    Content-Length fast path rejects before any parsing; bodies without a
    declared length (chunked/streamed) are counted while streaming and raise
    `RequestBodyTooLargeError`, which this middleware converts to a clean 413.
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger("at_shared.http_security")


# ---------------------------------------------------------------------------
# Response headers
# ---------------------------------------------------------------------------
def security_headers(*, is_production: bool = False) -> dict[str, str]:
    """OWASP-recommended response headers for a JSON API surface."""
    headers = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Cross-Origin-Opener-Policy": "same-origin",
        "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
        "Content-Security-Policy": "default-src 'none'",
        "Cache-Control": "no-store",
        "X-XSS-Protection": "0",
    }
    if is_production:
        headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return headers


# ---------------------------------------------------------------------------
# Request size limiting
# ---------------------------------------------------------------------------
class RequestBodyTooLargeError(Exception):
    """Raised while streaming a request body past the configured cap."""


def _content_length(scope: dict) -> int | None:
    for name, value in scope.get("headers", ()):
        if name == b"content-length":
            try:
                return int(value)
            except (TypeError, ValueError):
                return None
    return None


async def _reject_413(send) -> None:
    body = json.dumps({"detail": "request body too large", "code": "payload_too_large"}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class RequestSizeLimitMiddleware:
    """Pure-ASGI middleware enforcing a max request body size."""

    def __init__(self, app, *, max_body_bytes: int) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: dict, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        content_length = _content_length(scope)
        if content_length is not None and content_length > self.max_body_bytes:
            await _reject_413(send)
            return

        received = 0
        over = False

        async def limited_receive() -> dict:
            nonlocal received, over
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_body_bytes:
                    over = True
                    raise RequestBodyTooLargeError()
            return message

        response_started = False

        async def limited_send(message: dict) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, limited_send)
        except RequestBodyTooLargeError:
            if over and not response_started:
                await _reject_413(send)
            elif over:
                logger.warning(
                    "request body exceeded %s bytes after response started; aborting stream",
                    self.max_body_bytes,
                )


# ---------------------------------------------------------------------------
# One-call installer for FastAPI apps
# ---------------------------------------------------------------------------
def install_http_security(app, *, max_body_bytes: int, is_production: bool) -> None:
    """Add the request-size middleware + security headers to a FastAPI app.

    `app` is duck-typed (Starlette/FastAPI) so `at_shared` stays free of a
    framework dependency.
    """
    app.add_middleware(RequestSizeLimitMiddleware, max_body_bytes=max_body_bytes)

    @app.middleware("http")
    async def _security_headers(request, call_next):
        response = await call_next(request)
        for key, value in security_headers(is_production=is_production).items():
            response.headers.setdefault(key, value)
        return response
