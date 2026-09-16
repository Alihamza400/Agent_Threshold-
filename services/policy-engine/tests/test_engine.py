"""Policy Engine unit tests — determinism + fail-closed semantics."""

from __future__ import annotations

from at_shared.schemas.tx import DecisionType
from policy_engine.engine import EngineContext, EngineResult, PolicyData, evaluate

ALICE = "0x1111111111111111111111111111111111111111"
BOB = "0x2222222222222222222222222222222222222222"
EVE = "0x3333333333333333333333333333333333333333"
CAROL = "0x4444444444444444444444444444444444444444"


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


def test_empty_policy_all_defaults():
    p = base_policy()
    result = evaluate(p, BOB, 1_000, None, ctx())
    assert result.decision == DecisionType.APPROVE
    assert result.policy_version == 3


def test_multiple_deny_list_entries():
    p = base_policy(deny_list=(EVE, CAROL))
    result_eve = evaluate(p, EVE, 1_000, None, ctx())
    result_carol = evaluate(p, CAROL, 1_000, None, ctx())
    result_bob = evaluate(p, BOB, 1_000, None, ctx())
    assert result_eve.decision == DecisionType.REJECT
    assert result_carol.decision == DecisionType.REJECT
    assert result_bob.decision == DecisionType.APPROVE


def test_contract_deployment_to_address_none():
    p = base_policy()
    result = evaluate(p, None, 0, None, ctx())
    assert result.decision == DecisionType.APPROVE


def test_gas_ceiling_with_none_gas_used():
    p = base_policy(gas_ceiling=100_000)
    result = evaluate(p, BOB, 1_000, None, ctx())
    assert result.decision == DecisionType.APPROVE


def test_daily_spend_exactly_at_limit():
    p = base_policy(daily_spend_limit_usd=100.0)
    result = evaluate(p, BOB, 1_000, None, ctx(usd_value=50.0, daily_spend_used_usd=50.0))
    assert result.decision == DecisionType.APPROVE


def test_daily_spend_one_over_limit():
    p = base_policy(daily_spend_limit_usd=100.0)
    result = evaluate(p, BOB, 1_000, None, ctx(usd_value=50.01, daily_spend_used_usd=50.0))
    assert result.decision == DecisionType.REJECT


def test_rate_limit_exactly_at_limit():
    p = base_policy(rate_limit_per_minute=5)
    result = evaluate(p, BOB, 1_000, None, ctx(recent_tx_count=4))
    assert result.decision == DecisionType.APPROVE


def test_rate_limit_one_over():
    p = base_policy(rate_limit_per_minute=5)
    result = evaluate(p, BOB, 1_000, None, ctx(recent_tx_count=5))
    assert result.decision == DecisionType.REJECT


def test_time_window_boundary_at_from_minute():
    p = base_policy(active_from_minute=540, active_to_minute=1020)
    result = evaluate(p, BOB, 1_000, None, ctx(now_utc_minute=540))
    assert result.decision == DecisionType.APPROVE


def test_time_window_boundary_at_to_minute():
    p = base_policy(active_from_minute=540, active_to_minute=1020)
    result = evaluate(p, BOB, 1_000, None, ctx(now_utc_minute=1020))
    assert result.decision == DecisionType.REJECT


def test_time_window_inside():
    p = base_policy(active_from_minute=540, active_to_minute=1020)
    result = evaluate(p, BOB, 1_000, None, ctx(now_utc_minute=720))
    assert result.decision == DecisionType.APPROVE


def test_fail_closed_mode_disabled():
    p = base_policy()
    result = evaluate(p, BOB, 1_000, None, ctx(fail_closed=False))
    assert result.decision == DecisionType.ESCALATE
    assert any("fail-open" in r for r in result.reasons)


def test_anomaly_below_threshold_no_escalation():
    p = base_policy(anomaly_threshold=70.0)
    result = evaluate(p, BOB, 1_000, None, ctx(anomaly_score=69.9))
    assert result.decision != DecisionType.ESCALATE or not any(
        "anomaly" in r for r in result.reasons
    )


def test_anomaly_exactly_at_threshold():
    p = base_policy(anomaly_threshold=70.0)
    result = evaluate(p, BOB, 1_000, None, ctx(anomaly_score=70.0))
    assert result.decision == DecisionType.ESCALATE
    assert any("anomaly" in r for r in result.reasons)


def test_anomaly_none_score_not_evaluated():
    result = evaluate(base_policy(), BOB, 1_000, None, ctx(anomaly_score=None))
    assert result.decision == DecisionType.APPROVE


def test_policy_data_from_orm():
    from unittest.mock import MagicMock

    mock_policy = MagicMock()
    mock_policy.version = 5
    mock_policy.spend_limit_usd = 200.0
    mock_policy.daily_spend_limit_usd = 1000.0
    mock_policy.allow_list = [BOB]
    mock_policy.deny_list = [EVE]
    mock_policy.rate_limit_per_minute = 10
    mock_policy.active_from_minute = 600
    mock_policy.active_to_minute = 960
    mock_policy.gas_ceiling = 200_000
    mock_policy.anomaly_threshold = 60.0

    p = PolicyData.from_orm(mock_policy)
    assert p.version == 5
    assert p.spend_limit_usd == 200.0
    assert p.allow_list == (BOB,)
    assert p.deny_list == (EVE,)
    assert p.gas_ceiling == 200_000
    assert p.anomaly_threshold == 60.0


def test_policy_data_from_orm_none_lists():
    from unittest.mock import MagicMock

    mock_policy = MagicMock()
    mock_policy.version = 1
    mock_policy.spend_limit_usd = None
    mock_policy.daily_spend_limit_usd = None
    mock_policy.allow_list = None
    mock_policy.deny_list = None
    mock_policy.rate_limit_per_minute = None
    mock_policy.active_from_minute = None
    mock_policy.active_to_minute = None
    mock_policy.gas_ceiling = None
    mock_policy.anomaly_threshold = 70.0

    p = PolicyData.from_orm(mock_policy)
    assert p.allow_list == ()
    assert p.deny_list == ()


def test_engine_result_merge_approve_with_escalate():
    r = EngineResult(decision=DecisionType.APPROVE, reasons=[])
    r.merge(EngineResult(decision=DecisionType.ESCALATE, reasons=["anomaly"]))
    assert r.decision == DecisionType.ESCALATE
    assert r.reasons == ["anomaly"]


def test_engine_result_merge_approve_with_approve():
    r = EngineResult(decision=DecisionType.APPROVE, reasons=["a"])
    r.merge(EngineResult(decision=DecisionType.APPROVE, reasons=["b"]))
    assert r.decision == DecisionType.APPROVE
    assert r.reasons == ["a", "b"]


def test_engine_result_merge_reject_with_reject():
    r = EngineResult(decision=DecisionType.REJECT, reasons=["deny"])
    r.merge(EngineResult(decision=DecisionType.REJECT, reasons=["spend"]))
    assert r.decision == DecisionType.REJECT
    assert "deny" in r.reasons
    assert "spend" in r.reasons


def test_gas_ceiling_exactly_at_limit():
    p = base_policy(gas_ceiling=100_000)
    result = evaluate(p, BOB, 1_000, 100_000, ctx())
    assert result.decision == DecisionType.APPROVE


def test_spend_limit_exactly_at_limit():
    p = base_policy(spend_limit_usd=50.0)
    result = evaluate(p, BOB, 1_000, None, ctx(usd_value=50.0))
    assert result.decision == DecisionType.APPROVE


def test_usd_value_none_skips_spend_check():
    p = base_policy(spend_limit_usd=50.0)
    result = evaluate(p, BOB, 1_000, None, ctx(usd_value=None))
    assert result.decision != DecisionType.REJECT or not any(
        "spend limit" in r for r in result.reasons
    )


def test_deny_list_case_insensitive():
    p = base_policy(deny_list=("0xABCDEF" * 7 + "ABCD",))
    result = evaluate(p, "0xabcdef" * 7 + "abcd", 1_000, None, ctx())
    assert result.decision == DecisionType.REJECT


def test_allow_list_case_insensitive():
    addr_mixed = "0xABCDEF" * 7 + "ABCD"
    addr_lower = addr_mixed.lower()
    p = base_policy(allow_list=(addr_mixed,))
    result = evaluate(p, addr_lower, 1_000, None, ctx(known_counterparties=frozenset({addr_lower})))
    assert result.decision == DecisionType.APPROVE


def test_new_counterparty_zero_value_no_escalate():
    result = evaluate(base_policy(), CAROL, 0, None, ctx())
    assert result.decision == DecisionType.APPROVE
