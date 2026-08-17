"""Rate limiting: per-org + per-agent token bucket via Redis (FR throttle).

Fail-closed: if Redis is unreachable, requests are REJECTED with 503 rather
than allowed through unlimited (protects against DoS exhausting screening).
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from redis import RedisError

from app.redis_client import redis_client

_BUCKET_CAPACITY = 200
_REFILL_PER_SEC = 10


def _token_bucket_allowed(key: str, capacity: int, refill_per_sec: float) -> tuple[bool, int]:
    """Atomic Lua token bucket. Returns (allowed, retry_after_seconds)."""
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
    import time

    try:
        allowed, retry = redis_client.eval(
            lua, 1, key, capacity, refill_per_sec, time.time()
        )
        return bool(allowed), int(retry)
    except RedisError:
        # Fail-closed: cannot verify quota -> 503
        return False, -1


def rate_limit_middleware(app: FastAPI, capacity: int = _BUCKET_CAPACITY, refill_per_sec: float = _REFILL_PER_SEC) -> Callable:
    """ASGI middleware factory keyed by org_id/agent_id when present."""

    async def middleware(request: Request, call_next):
        # Skip rate limiting for ops/health routes
        if request.url.path.startswith(("/healthz", "/readyz", "/docs", "/redoc", "/openapi.json")):
            return await call_next(request)

        org_id = request.headers.get("x-org-id")
        key = f"rl:{org_id or 'anon'}"
        allowed, retry_after = _token_bucket_allowed(key, capacity, refill_per_sec)
        if not allowed:
            status = 503 if retry_after < 0 else 429
            return JSONResponse(
                status_code=status,
                content={
                    "detail": "rate limit exceeded",
                    "code": "rate_limited",
                    "retry_after_seconds": max(retry_after, 0),
                },
                headers={"Retry-After": str(max(retry_after, 0))},
            )
        return await call_next(request)

    return middleware