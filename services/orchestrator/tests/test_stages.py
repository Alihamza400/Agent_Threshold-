"""Per-stage budget runner (8.3): bounded execution + timeout fail-closed."""

from __future__ import annotations

import asyncio

import pytest
from orchestrator.errors import StageBudgetError, StageError
from orchestrator.stages import StageBudget, run_stage


@pytest.mark.asyncio
async def test_stage_success_records_timing():
    value, timing = await run_stage("classifier", 1.0, asyncio.sleep(0.001, result="ok"))
    assert value == "ok"
    assert timing.ok
    assert timing.name == "classifier"
    assert timing.duration_ms >= 0
    assert not timing.timed_out


@pytest.mark.asyncio
async def test_stage_timeout_raises():
    with pytest.raises(StageBudgetError):
        await run_stage("simulation", 0.01, asyncio.sleep(1.0))


@pytest.mark.asyncio
async def test_stage_error_raises():
    async def boom() -> None:
        raise RuntimeError("boom")

    with pytest.raises(StageError):
        await run_stage("policy", 0.1, boom())


def test_budget_lookup():
    budgets = StageBudget()
    assert budgets.for_stage("classifier") == 1.0
    assert budgets.for_stage("simulation") == 1.2
    with pytest.raises(KeyError):
        budgets.for_stage("unknown_stage")


def test_budgets_honor_slos():
    """Each stage ceiling satisfies its own SLO; the hot path stays bounded."""
    budgets = StageBudget()
    assert budgets.simulation <= 1.2  # TRD p95 simulation < 1.2s
    assert budgets.classifier <= 1.0  # LLM bounded timeout 800ms + slack
    for name in ("kill_switch", "resolve", "context", "policy"):
        assert getattr(budgets, name) <= 0.2  # deterministic stages stay cheap

    hot_path = sum(
        getattr(budgets, name)
        for name in ("kill_switch", "resolve", "classifier", "simulation", "context", "policy")
    )
    assert hot_path < 3.0  # worst-case ceiling bounded even with a slow stage
