"""Shared Redis client and fail-closed token-bucket rate limiter.

Used by every service that needs short-lived counters / nonce locks:
  - api-gateway: per-org / per-agent request throttling
  - mcp-server: per-key tool-call throttling
  - execution-adapter: Redis-locked nonce allocation (Phase 5)

Fail-closed: if Redis is unreachable the limiter REJECTS the request
(returns `retry_after=-1`) rather than allowing it through unlimited.
"""

from __future__ import annotations

import time

import redis

from at_shared.config import get_settings

_settings = get_settings()

redis_client = redis.Redis.from_url(
    _settings.redis_url,
    decode_responses=True,
    socket_connect_timeout=2,
    socket_timeout=2,
    max_connections=20,
)


def ping_redis() -> bool:
    try:
        return bool(redis_client.ping())
    except redis.RedisError:
        return False


def token_bucket_allowed(
    key: str,
    capacity: int,
    refill_per_sec: float,
) -> tuple[bool, int]:
    """Atomic Lua token bucket. Returns (allowed, retry_after_seconds).

    `retry_after == -1` signals Redis is unavailable (fail-closed reject).
    """
    lua = """
    local key = KEYS[1]
    local capacity = tonumber(ARGV[1])
    local refill = tonumber(ARGV[2])
    local now = tonumber(ARGV[3])
    local data = redis.call('HMGET', key, 'tokens', 'ts')
    local tokens = tonumber(data[1]) or capacity
    local ts = tonumber(data[2]) or now
    tokens = math.min(capacity, tokens + (now - ts) * refill)
    if tokens >= 1 then
        redis.call('HMSET', key, 'tokens', tokens - 1, 'ts', now)
        redis.call('EXPIRE', key, 60)
        return {1, 0}
    end
    redis.call('HMSET', key, 'tokens', tokens, 'ts', now)
    local retry = math.ceil((1 - tokens) / refill)
    return {0, retry}
    """
    try:
        allowed, retry = redis_client.eval(
            lua, 1, key, capacity, refill_per_sec, time.time()
        )
        return bool(allowed), int(retry)
    except redis.RedisError:
        return False, -1