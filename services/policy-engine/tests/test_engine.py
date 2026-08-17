"""Policy Engine unit tests — determinism + fail-closed semantics."""

from __future__ import annotations

from at_shared.schemas.tx import DecisionType
from policy_engine.engine import EngineContext, EngineResult, PolicyData, evaluate

ALICE = "0x1111111111111111111111111111111111111111"
BOB = "0x2222222222222222222222222222222222222222"
EVE = "0x3333333333333333333333333333333333333333"


def base_policy(**overrides) -> PolicyData:
    defaults = dict(
        version=3,
        spend_limit_usd=None,
        daily_spend_limit_usd=None,
        allow_list=(),
        deny_list=(),
        rate_limit_per_minute=None,
        active_from_minute=None,
        active_to_minute=None,
        gas_ceiling=None,
        anomaly_threshold=70.0,
    )
    defaults.update(overrides)
    return PolicyData(**defaults)


def ctx(**overrides) -> EngineContext:
    defaults = dict(usd_value=10.0, known_counterparties=frozenset({BOB}), anomaly_score=None)
    defaults.update(overrides)
    return EngineContext(**defaults)


def test_approve_within_policy():
    result = evaluate(base_policy(), BOB, 1_000, None, ctx())
    assert result.decision == DecisionType.APPROVE


def test_reject_deny_list():
    p = base_policy(deny_list=(EVE,))
    result = evaluate(p, EVE, 1_000, None, ctx())
    assert result.decision == DecisionType.REJECT
    assert any("deny list" in r for r in result.reasons)


def test_reject_not_in_allow_list():
    p = base_policy(allow_list=(BOB,))
    result = evaluate(p, EVE, 1_000, None, ctx())
    assert result.decision == DecisionType.REJECT
    assert any("allow list" in r for r in result.reasons)


def test_approve_in_allow_list():
    p = base_policy(allow_list=(BOB,))
    result = evaluate(p, BOB, 1_000, None, ctx())
    assert result.decision == DecisionType.APPROVE


def test_reject_over_spend_limit():
    p = base_policy(spend_limit_usd=50.0)
    result = evaluate(p, BOB, 1_000, None, ctx(usd_value=100.0))
    assert result.decision == DecisionType.REJECT
    assert any("spend limit" in r for r in result.reasons)


def test_reject_daily_limit_breach():
    p = base_policy(daily_spend_limit_usd=100.0)
    result = evaluate(p, BOB, 1_000, None, ctx(usd_value=60.0, daily_spend_used_usd=50.0))
    assert result.decision == DecisionType.REJECT
    assert any("daily spend limit" in r for r in result.reasons)


def test_reject_rate_limit():
    p = base_policy(rate_limit_per_minute=5)
    result = evaluate(p, BOB, 1_000, None, ctx(recent_tx_count=5))
    assert result.decision == DecisionType.REJECT
    assert any("rate limit" in r for r in result.reasons)


def test_reject_outside_time_window():
    p = base_policy(active_from_minute=540, active_to_minute=1020)  # 09:00-17:00 UTC
    result = evaluate(p, BOB, 1_000, None, ctx(now_utc_minute=60))
    assert result.decision == DecisionType.REJECT
    assert any("time window" in r for r in result.reasons)


def test_reject_gas_over_ceiling():
    p = base_policy(gas_ceiling=100_000)
    result = evaluate(p, BOB, 1_000, 500_000, ctx())
    assert result.decision == DecisionType.REJECT
    assert any("gas" in r for r in result.reasons)


def test_escalate_on_high_anomaly():
    result = evaluate(base_policy(), BOB, 1_000, None, ctx(anomaly_score=90.0))
    assert result.decision == DecisionType.ESCALATE
    assert any("anomaly" in r for r in result.reasons)


def test_escalate_on_new_counterparty():
    result = evaluate(base_policy(), EVE, 1_000, None, ctx())
    assert result.decision == DecisionType.ESCALATE
    assert any("unseen" in r for r in result.reasons)


def test_known_counterparty_does_not_escalate():
    result = evaluate(base_policy(), BOB, 1_000, None, ctx(known_counterparties=frozenset({BOB})))
    assert result.decision == DecisionType.APPROVE


def test_escalate_without_value_does_not_trigger_new_cp():
    # zero-value interaction with new counterparty: approved (read-only call pattern)
    result = evaluate(base_policy(), EVE, 0, None, ctx(known_counterparties=frozenset({BOB})))
    assert result.decision == DecisionType.APPROVE


def test_reject_wins_over_escalate():
    p = base_policy(spend_limit_usd=50.0)
    result = evaluate(p, EVE, 1_000, None, ctx(usd_value=100.0, anomaly_score=95.0))
    assert result.decision == DecisionType.REJECT


def test_deterministic_for_identical_input():
    a = evaluate(base_policy(), BOB, 1_000, None, ctx(anomaly_score=40.0))
    b = evaluate(base_policy(), BOB, 1_000, None, ctx(anomaly_score=40.0))
    assert a.decision == b.decision and a.reasons == b.reasons


def test_merge_harshest_wins():
    r = EngineResult(decision=DecisionType.ESCALATE, reasons=["a"])
    r.merge(EngineResult(decision=DecisionType.REJECT, reasons=["b"]))
    assert r.decision == DecisionType.REJECT
    assert r.reasons == ["a", "b"]