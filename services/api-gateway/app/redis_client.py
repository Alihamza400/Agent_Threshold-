"""Redis client for nonce locks, rate-limit counters, and short-lived caches.

Uses a connection pool; fails fast rather than queueing (fail-closed
behavior for the screening hot path).
"""

from __future__ import annotations

import redis
from at_shared.config import get_settings

settings = get_settings()

redis_client = redis.Redis.from_url(
    settings.redis_url,
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