"""AgentThreshold MCP server — Streamable HTTP + auth middleware.

Serves read-only tools (FR-MCP-01, FR-MCP-02) over the official MCP
transport. Every request is authenticated and signed:

  1. X-API-Key  -> resolved to org + agent scope (fail-closed).
  2. X-MCP-Timestamp + X-MCP-Signature -> HMAC-SHA256 over `ts:body` using the
     raw API key as secret (task 4.3, replay window 300s).
  3. Per-key token-bucket rate limit (fail-closed on Redis outage).
  4. Tool call -> allow-list check at call time, then handler with the auth
     context bound via contextvar.

mTLS is enforced at the ingress/TLS layer in production (infra); this
middleware is transport-agnostic and runs behind it.
"""

from __future__ import annotations

from collections.abc import Callable

from at_shared.db import SessionLocal
from at_shared.redis import token_bucket_allowed
from at_shared.schemas.tx import ChainId
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from mcp_server import auth as mcp_auth
from mcp_server.errors import MCPAuthError
from mcp_server.registry import assert_tool_allowed
from mcp_server.schemas import (
    HistoryResult,
    PolicyRead,
    SimulateRequest,
    SimulationResult,
)
from mcp_server.tools.history import get_agent_history
from mcp_server.tools.policy import get_policy
from mcp_server.tools.simulate import simulate_transaction

_RATE_LIMIT_CAPACITY = 60
_RATE_LIMIT_REFILL_PER_SEC = 10.0

server = MCPServer(name="agentthreshold-mcp", version="0.1.0")


# --------------------------------------------------------------------------
# Tool surface (all read-only; allow-list enforced per call)
# --------------------------------------------------------------------------
@server.tool(name="simulate_transaction")
async def simulate_transaction_tool(
    agent_id: str,
    chain_id: ChainId,
    from_address: str,
    to_address: str | None,
    value_wei: int,
    calldata: str | None,
) -> SimulationResult:
    assert_tool_allowed("simulate_transaction")
    return await simulate_transaction(
        SimulateRequest(
            agent_id=agent_id,
            chain_id=chain_id,
            from_address=from_address,
            to_address=to_address,
            value_wei=value_wei,
            calldata=calldata,
        )
    )


@server.tool(name="get_policy")
def get_policy_tool(agent_id: str) -> PolicyRead:
    assert_tool_allowed("get_policy")
    return get_policy(agent_id)


@server.tool(name="get_agent_history")
def get_agent_history_tool(agent_id: str, limit: int = 20) -> HistoryResult:
    assert_tool_allowed("get_agent_history")
    return get_agent_history(agent_id, limit=limit)


# --------------------------------------------------------------------------
# Auth middleware (pure ASGI — forwards lifespan so the MCP session-manager
# task group actually starts)
# --------------------------------------------------------------------------
async def _buffer_body(receive: Receive) -> tuple[bytes, Callable[[], Receive]]:
    chunks: list[bytes] = []
    while True:
        message = await receive()
        if message["type"] == "http.request":
            chunks.append(message.get("body", b""))
            if not message.get("more_body", False):
                break
    body = b"".join(chunks)

    def replay() -> Receive:
        sent = False

        async def inner() -> dict:
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            # Fall through to the real receive after the buffered body: SSE
            # streaming responses (EventSourceResponse._listen_for_disconnect)
            # must BLOCK on receive() the way the raw ASGI receive does — an
            # instantly-returning receive busy-spins and starves the event loop.
            return await receive()

        return inner

    return body, replay


def _header(scope: Scope, name: str) -> str | None:
    target = name.encode("latin-1")
    for key, value in scope["headers"]:
        if key == target:
            return value.decode("latin-1")
    return None


class _SignedRequestASGIMiddleware:
    def __init__(self, inner: ASGIApp) -> None:
        self.inner = inner

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            await self.inner(scope, receive, send)
            return
        if scope["type"] != "http":
            await self.inner(scope, receive, send)
            return

        path = scope["path"]
        if path in ("/healthz", "/readyz"):
            response = JSONResponse({"status": "ok", "service": "mcp-server"})
            await response(scope, receive, send)
            return

        body, replay = await _buffer_body(receive)

        raw_key = _header(scope, "x-api-key")
        timestamp = _header(scope, "x-mcp-timestamp")
        signature = _header(scope, "x-mcp-signature")

        db = SessionLocal()
        try:
            try:
                ctx = mcp_auth.validate_api_key(db, raw_key)
                mcp_auth.verify_signature(raw_key, timestamp, body, signature)
            except MCPAuthError as exc:
                response = JSONResponse({"error": exc.message}, status_code=401)
                await response(scope, receive, send)
                return

            allowed, retry_after = token_bucket_allowed(
                f"mcp:key:{ctx.key_id}", _RATE_LIMIT_CAPACITY, _RATE_LIMIT_REFILL_PER_SEC
            )
            if not allowed:
                code = 429 if retry_after >= 0 else 503
                detail = "rate limit exceeded" if retry_after >= 0 else "rate limiter unavailable"
                response = JSONResponse({"error": detail}, status_code=code)
                await response(scope, receive, send)
                return

            mcp_auth.bind_auth_context(ctx)
        finally:
            db.close()

        try:
            await self.inner(scope, replay(), send)
        finally:
            mcp_auth.reset_auth_context()


def create_app(
    transport_security: TransportSecuritySettings | None = None,
    json_response: bool = False,
) -> ASGIApp:
    mcp_app = server.streamable_http_app(
        transport_security=transport_security,
        json_response=json_response,
    )
    return _SignedRequestASGIMiddleware(mcp_app)


app = create_app()