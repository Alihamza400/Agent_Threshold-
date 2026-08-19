"""Single-use decision tokens (task 8.5).

The Execution Adapter authorizes exactly ONE broadcast per approved decision.
A decision token is issued at `prepare` and consumed atomically at `submit`;
a second use of the same token is rejected. This closes the race/bypass
threat from TRD Section 8 ("execution requires a valid, single-use decision
token issued only by the Orchestrator").

Guarantees:
  - consume() is a single atomic Lua script (GET + compare + DEL), so two
    concurrent submits can never both pass.
  - Tokens expire after `ttl_seconds` (default 300s). After expiry a new
    token MUST be re-issued — re-approval is NOT automatic (fail-closed).
  - Redis failure fails closed: consume() returns False (no broadcast),
    issue() raises TokenStoreError.
"""

from __future__ import annotations

import secrets

import redis
from at_shared.redis import redis_client

from execution_service.errors import TokenStoreError

_TOKEN_LUA = """
local key = KEYS[1]
local token = ARGV[1]
local existing = redis.call('GET', key)
if not existing then
    return 0
end
if existing == token then
    redis.call('DEL', key)
    return 1
end
return 0
"""


def _token_key(decision_id: str) -> str:
    return f"execution:decision:{decision_id}:token"


class DecisionTokenStore:
    """Redis-backed, single-use decision-token authority for the adapter."""

    def __init__(self, client: redis.Redis | None = None, ttl_seconds: int = 300) -> None:
        self._client = client or redis_client
        self.ttl_seconds = ttl_seconds

    def issue(self, decision_id: str) -> str:
        """Mint a fresh token for a decision (idempotent within TTL).

        A concurrent second issue for the same decision overwrites the first,
        so callers must serialize on `prepare` (the DB state guard handles the
        only race: status='approved' conditional transition).
        """
        token = secrets.token_urlsafe(32)
        try:
            self._client.set(_token_key(decision_id), token, ex=self.ttl_seconds)
        except redis.RedisError as exc:
            raise TokenStoreError(f"cannot issue decision token: {exc}") from exc
        return token

    def consume(self, decision_id: str, token: str) -> bool:
        """Atomically consume the token. True only for the single winning call."""
        try:
            return bool(self._client.eval(_TOKEN_LUA, 1, _token_key(decision_id), token))
        except redis.RedisError as exc:
            raise TokenStoreError(f"cannot consume decision token: {exc}") from exc

    def revoke(self, decision_id: str) -> None:
        """Force-invalidate any outstanding token (cancel path)."""
        try:
            self._client.delete(_token_key(decision_id))
        except redis.RedisError as exc:
            raise TokenStoreError(f"cannot revoke decision token: {exc}") from exc
