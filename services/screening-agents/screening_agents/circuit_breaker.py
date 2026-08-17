"""Circuit breaker for LLM calls (fail-closed reliability).

Trips after `failure_threshold` consecutive failures, then refuses calls for
`cooldown_seconds`. Tripped state returns `is_open() == True` so the
orchestrator can fail closed without waiting on a dead provider.
"""

from __future__ import annotations

import threading
import time


class CircuitBreaker:
    def __init__(self, failure_threshold: int = 3, cooldown_seconds: float = 15.0):
        self._failure_threshold = failure_threshold
        self._cooldown_seconds = cooldown_seconds
        self._consecutive_failures = 0
        self._opened_at: float | None = None
        self._lock = threading.Lock()

    def is_open(self) -> bool:
        with self._lock:
            if self._opened_at is None:
                return False
            return time.monotonic() - self._opened_at < self._cooldown_seconds

    def record_success(self) -> None:
        with self._lock:
            self._consecutive_failures = 0
            self._opened_at = None

    def record_failure(self) -> None:
        with self._lock:
            self._consecutive_failures += 1
            if self._consecutive_failures >= self._failure_threshold:
                self._opened_at = time.monotonic()