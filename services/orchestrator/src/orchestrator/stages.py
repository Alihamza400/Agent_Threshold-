"""Per-stage execution budgets + bounded stage runner (8.3).

Every pipeline stage runs inside `asyncio.wait_for` with its own wall-clock
budget. A dead dependency (LLM, RPC, DB) therefore surfaces as a timeout
instead of stalling the hot path; the pipeline maps each timeout to a
fail-closed decision (SR-04).

Budgets are tuned so the happy path stays inside the p95 < 2s end-to-end SLO:
  - classifier 1.0s  (LLM bounded timeout 800ms + slack)
  - simulation 1.2s  (TRD p95 simulation < 1.2s)
  - every deterministic stage < 100ms (these are DB + pure math only)
The hot-path ceiling (kill_switch + resolve + classifier + simulation +
context + policy) stays under 3s worst case; typical latencies are far lower.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Any

from orchestrator.errors import StageBudgetError, StageError


@dataclass(frozen=True)
class StageBudget:
    """Wall-clock budget (seconds) per pipeline stage."""

    kill_switch: float = 0.05
    resolve: float = 0.05
    classifier: float = 1.00
    simulation: float = 1.20
    context: float = 0.10
    policy: float = 0.05
    interpreter: float = 1.00
    escalation_draft: float = 1.00

    def for_stage(self, name: str) -> float:
        if not hasattr(self, name):
            raise KeyError(f"no budget configured for stage '{name}'")
        return getattr(self, name)


@dataclass
class StageTiming:
    """Observability record for one pipeline stage."""

    name: str
    started_ms: int = 0
    duration_ms: int = 0
    timed_out: bool = False
    error: str | None = None

    @property
    def ok(self) -> bool:
        return not self.timed_out and self.error is None


async def run_stage(
    name: str,
    budget: float,
    coro: Awaitable[Any],
    *,
    started_ms: int = 0,
) -> tuple[Any, StageTiming]:
    """Run `coro` under a wall-clock budget.

    Returns ``(value, timing)`` on success. Raises ``StageBudgetError`` on
    timeout and ``StageError`` on any other exception. The caller decides the
    fail-closed mapping.
    """
    t0 = time.monotonic()
    timing = StageTiming(name=name, started_ms=started_ms)
    try:
        value = await asyncio.wait_for(coro, timeout=budget)
    except TimeoutError:
        timing.duration_ms = int((time.monotonic() - t0) * 1000)
        timing.timed_out = True
        raise StageBudgetError(name, budget) from None
    except Exception as exc:
        timing.duration_ms = int((time.monotonic() - t0) * 1000)
        timing.error = str(exc)
        raise StageError(name, exc) from exc
    timing.duration_ms = int((time.monotonic() - t0) * 1000)
    return value, timing
