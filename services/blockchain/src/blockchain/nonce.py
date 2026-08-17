"""Redis-locked sequenced nonce allocation (FR-CHAIN-03).

No two concurrent requests for the same agent wallet may receive the same
nonce. Allocation is a single atomic Lua script:

  - if no counter exists for the wallet, seed it from the on-chain pending
    nonce (eth_getTransactionCount ... 'pending');
  - otherwise atomically INCR.

Redis errors fail closed (raise NonceReservationError) rather than assigning
a possibly-duplicated nonce. Reservations are also recorded in a hash so a
later executor can release/confirm them (Phase 6).
"""

from __future__ import annotations

import redis
from at_shared.redis import redis_client

from blockchain.errors import NonceReservationError

_NONCE_SEED_LUA = """
local counter_key = KEYS[1]
local reservation_key = KEYS[2]
local base = tonumber(ARGV[1])
local current = redis.call('GET', counter_key)
if not current then
    current = base
    redis.call('SET', counter_key, current)
end
local nonce = tonumber(current)
redis.call('SET', counter_key, nonce + 1)
redis.call('HSET', reservation_key, tostring(nonce), 'reserved')
return nonce
"""


class NonceAllocator:
    """Thread-safe, process-safe nonce allocator backed by Redis."""

    def __init__(
        self,
        client: redis.Redis | None = None,
        sync_nonce_getter=None,
    ) -> None:
        self._client = client or redis_client
        # sync_nonce_getter(wallet) -> on-chain pending nonce; injected so the
        # blockchain RPC stays out of this module (testability).
        self._sync_nonce_getter = sync_nonce_getter or (lambda _wallet: 0)

    def _base_nonce(self, wallet: str) -> int:
        try:
            return int(self._sync_nonce_getter(wallet))
        except Exception as exc:  # noqa: BLE001 - fail closed on RPC failure
            raise NonceReservationError(
                f"cannot fetch base nonce for {wallet}: {exc}"
            ) from exc

    def reserve(self, wallet: str) -> int:
        """Reserve the next unique nonce for a wallet (atomic)."""
        base = self._base_nonce(wallet)
        try:
            nonce = self._client.eval(
                _NONCE_SEED_LUA,
                2,
                self._counter_key(wallet),
                self._reservation_key(wallet),
                base,
            )
        except redis.RedisError as exc:
            raise NonceReservationError(f"nonce allocation failed for {wallet}: {exc}") from exc
        return int(nonce)

    @staticmethod
    def _counter_key(wallet: str) -> str:
        return f"nonce:{wallet}:counter"

    @staticmethod
    def _reservation_key(wallet: str) -> str:
        return f"nonce:{wallet}:reservations"

    def reservations(self, wallet: str) -> dict[str, str]:
        """All reserved nonces for a wallet (status map)."""
        try:
            return self._client.hgetall(self._reservation_key(wallet)) or {}
        except redis.RedisError as exc:
            raise NonceReservationError(f"cannot read reservations for {wallet}: {exc}") from exc