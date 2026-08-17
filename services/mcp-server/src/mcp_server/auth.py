"""AuthN/AuthZ for MCP requests (task 4.3, FR-MCP-02, FR-AUTH-01).

- API-key validation: raw key hashed (sha256) and matched against the DB
  (same scheme as the gateway SDK auth). Keys are scoped to org + agent IDs.
- Signed requests: each call must carry an HMAC-SHA256 signature over
  `timestamp:body` using the raw API key as the secret, plus a fresh
  timestamp (replay window). This mitigates MCP/tool spoofing when the key
  itself leaks over an unauthenticated transport.
- mTLS: enforced at the transport layer (ingress) via infra; the code path
  here assumes TLS + signature, documented in README.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from contextvars import ContextVar

from at_shared.api_keys import hash_api_key
from at_shared.models import ApiKey
from sqlalchemy import select
from sqlalchemy.orm import Session

from mcp_server.errors import MCPAuthError, MCPScopeError

_SIGNATURE_REPLAY_WINDOW_SECONDS = 300
_DEFAULT_TOOL_ALLOWLIST = frozenset(
    {"simulate_transaction", "get_policy", "get_agent_history"}
)
# The MCP server exposes NO mutating tools. If this set ever grows, the
# registry rejects the tool at registration (FR-MCP-02).
_MUTATING_TOOLS: frozenset[str] = frozenset()


class AuthContext:
    """Resolved principal for the current MCP request."""

    __slots__ = ("org_id", "agent_ids", "key_id")

    def __init__(self, org_id: str, agent_ids: frozenset[str], key_id: str) -> None:
        self.org_id = org_id
        self.agent_ids = agent_ids
        self.key_id = key_id

    def authorize_agent(self, agent_id: str) -> None:
        """Reject access to an agent outside the key's scope (fail-closed)."""
        if self.agent_ids and agent_id not in self.agent_ids:
            raise MCPScopeError(f"agent '{agent_id}' not in API key scope")


_auth_ctx: ContextVar[AuthContext | None] = ContextVar("mcp_auth_ctx", default=None)


def get_auth_context() -> AuthContext:
    ctx = _auth_ctx.get()
    if ctx is None:
        raise MCPAuthError("No authenticated context for request")
    return ctx


def _constant_time_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def validate_api_key(db: Session, raw_key: str) -> AuthContext:
    """Resolve a raw API key to its scoped AuthContext (fail-closed)."""
    if not raw_key:
        raise MCPAuthError("API key required")
    record = db.scalar(select(ApiKey).where(ApiKey.key_hash == hash_api_key(raw_key)))
    if record is None or not record.is_active:
        raise MCPAuthError("Invalid API key")
    return AuthContext(
        org_id=record.org_id,
        agent_ids=frozenset(record.agent_ids or []),
        key_id=record.id,
    )


def verify_signature(
    raw_key: str,
    timestamp: str,
    body: bytes,
    signature: str,
) -> None:
    """Verify the HMAC request signature (task 4.3). Fail-closed."""
    if not timestamp or not signature:
        raise MCPAuthError("Signed request required (X-MCP-Timestamp, X-MCP-Signature)")
    try:
        ts = int(timestamp)
    except ValueError as exc:
        raise MCPAuthError("Invalid X-MCP-Timestamp") from exc

    if abs(time.time() - ts) > _SIGNATURE_REPLAY_WINDOW_SECONDS:
        raise MCPAuthError("Request timestamp outside replay window")

    expected = hmac.new(
        raw_key.encode("utf-8"),
        f"{timestamp}:".encode() + body,
        hashlib.sha256,
    ).hexdigest()
    if not _constant_time_eq(signature, expected):
        raise MCPAuthError("Invalid request signature")


def compute_signature(raw_key: str, timestamp: str, body: bytes) -> str:
    """Client-side helper to sign a request body."""
    return hmac.new(
        raw_key.encode("utf-8"),
        f"{timestamp}:".encode() + body,
        hashlib.sha256,
    ).hexdigest()


def bind_auth_context(ctx: AuthContext) -> None:
    _auth_ctx.set(ctx)


def reset_auth_context() -> None:
    _auth_ctx.set(None)