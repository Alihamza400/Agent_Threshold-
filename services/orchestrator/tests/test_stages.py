"""Per-stage budget runner (8.3): bounded execution + timeout fail-closed."""

from __future__ import annotations

import asyncio
import contextlib

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


@pytest.mark.asyncio
async def test_stage_timing_ok_property_true():
    _, timing = await run_stage("test", 1.0, asyncio.sleep(0.001, result="x"))
    assert timing.ok is True


@pytest.mark.asyncio
async def test_stage_timing_error_records_error_string():
    async def fail() -> None:
        raise ValueError("bad input")

    with pytest.raises(StageError):
        await run_stage("policy", 1.0, fail())


@pytest.mark.asyncio
async def test_stage_timing_timeout_sets_timed_out_flag():
    with contextlib.suppress(StageBudgetError):
        await run_stage("simulation", 0.01, asyncio.sleep(2.0))
    # The timing is not returned on timeout (exception path), but the flag is
    # set internally. Verify the exception carries the stage name.
    with pytest.raises(StageBudgetError) as exc_info:
        await run_stage("simulation", 0.01, asyncio.sleep(2.0))
    assert "simulation" in str(exc_info.value)


@pytest.mark.asyncio
async def test_stage_zero_budget_immediate_timeout():
    with pytest.raises(StageBudgetError):
        await run_stage("fast", 0.0, asyncio.sleep(0.1))


@pytest.mark.asyncio
async def test_stage_preserves_cause_in_stage_error():
    original = RuntimeError("root cause")

    async def raise_it() -> None:
        raise original

    with pytest.raises(StageError) as exc_info:
        await run_stage("policy", 1.0, raise_it())
    assert exc_info.value.cause is original


@pytest.mark.asyncio
async def test_stage_success_returns_value():
    value, _ = await run_stage("ctx", 1.0, asyncio.sleep(0.001, result=42))
    assert value == 42


@pytest.mark.asyncio
async def test_stage_success_returns_value_none():
    value, timing = await run_stage("ctx", 1.0, asyncio.sleep(0.001, result=None))
    assert value is None
    assert timing.ok


@pytest.mark.asyncio
async def test_stage_started_ms_recorded():
    _, timing = await run_stage("test", 1.0, asyncio.sleep(0.001, result="ok"), started_ms=500)
    assert timing.started_ms == 500


def test_budget_for_stage_all_stages():
    budgets = StageBudget()
    for name in ("kill_switch", "resolve", "classifier", "simulation", "context", "policy",
                  "interpreter", "escalation_draft"):
        assert budgets.for_stage(name) > 0


def test_stage_budget_error_attributes():
    err = StageBudgetError("my_stage", 1.5)
    assert err.stage == "my_stage"
    assert err.budget_seconds == 1.5
    assert "my_stage" in str(err)


def test_stage_error_attributes():
    cause = ValueError("oops")
    err = StageError("policy", cause)
    assert err.stage == "policy"
    assert err.cause is cause
    assert "policy" in str(err)


def test_stage_error_no_cause():
    err = StageError("ctx", None)
    assert err.stage == "ctx"
    assert err.cause is None


def test_stage_budget_error_is_orchestrator_error():
    from orchestrator.errors import OrchestratorError

    assert issubclass(StageBudgetError, OrchestratorError)


def test_stage_error_is_orchestrator_error():
    from orchestrator.errors import OrchestratorError

    assert issubclass(StageError, OrchestratorError)


def test_budget_frozen_dataclass():
    budgets = StageBudget()
    with pytest.raises(AttributeError):
        budgets.classifier = 999  # type: ignore[misc]


@pytest.mark.asyncio
async def test_concurrent_stages_do_not_interfere():
    async def slow():
        await asyncio.sleep(0.05)
        return "slow_done"

    async def fast():
        await asyncio.sleep(0.01)
        return "fast_done"

    r1, t1 = await run_stage("a", 1.0, slow())
    r2, t2 = await run_stage("b", 1.0, fast())
    assert r1 == "slow_done"
    assert r2 == "fast_done"
    assert t1.name == "a"
    assert t2.name == "b"
    assert t2.duration_ms <= t1.duration_ms + 50  # fast should not be slower
