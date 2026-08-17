"""Anomaly Scorer unit tests — determinism + sensitivity (FR-AI-02)."""

from __future__ import annotations

from anomaly_scorer.baseline import BaselineFeatures, aggregate
from anomaly_scorer.scorer import score_transaction

CP_A = "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
CP_B = "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"


def make_baseline(**overrides) -> BaselineFeatures:
    defaults = dict(
        tx_count=200,
        total_volume_wei=200_000 * 10**18,
        mean_value_wei=1000 * 10**18,
        median_value_wei=500 * 10**18,
        std_value_wei=300 * 10**18,
        avg_freq_per_day=4.0,
        unique_counterparties=3,
        top_counterparty_share=0.8,
        unique_value_ratio=0.5,
    )
    defaults.update(overrides)
    return BaselineFeatures(**defaults)


def test_normal_value_low_score():
    result = score_transaction(make_baseline(), value_wei=500 * 10**18, to_address=CP_A, recent_tx_count=3)
    assert result.score < 40


def test_large_value_high_score():
    result = score_transaction(make_baseline(), value_wei=50_000 * 10**18, to_address=CP_A, recent_tx_count=3)
    assert result.score >= 60
    factors = {f["factor"]: f for f in result.contributing_factors}
    assert "value_outlier" in factors


def test_frequency_spike_flags():
    low = score_transaction(make_baseline(), value_wei=500 * 10**18, to_address=CP_A, recent_tx_count=0)
    high = score_transaction(make_baseline(), value_wei=500 * 10**18, to_address=CP_A, recent_tx_count=120)
    assert high.score > low.score
    factors = {f["factor"]: f for f in high.contributing_factors}
    assert "frequency_spike" in factors


def test_new_counterparty_scores_high():
    known = score_transaction(make_baseline(), value_wei=500 * 10**18, to_address=CP_A, recent_tx_count=3)
    new = score_transaction(make_baseline(), value_wei=500 * 10**18, to_address=CP_B, recent_tx_count=3, is_new_counterparty=True)
    assert new.score > known.score + 15  # 0.25 weight * 100
    factors = {f["factor"]: f for f in new.contributing_factors}
    assert "new_counterparty" in factors
    assert "first interaction" in factors["new_counterparty"]["detail"]


def test_empty_baseline_scores_zero():
    empty = BaselineFeatures(
        tx_count=0, total_volume_wei=0, mean_value_wei=0.0, median_value_wei=0.0,
        std_value_wei=0.0, avg_freq_per_day=0.0, unique_counterparties=0,
        top_counterparty_share=0.0, unique_value_ratio=0.0,
    )
    result = score_transaction(empty, value_wei=10**18, to_address=CP_A, recent_tx_count=1)
    assert result.score == 0.0
    assert result.is_anomalous is False


def test_deterministic_for_identical_input():
    a = score_transaction(make_baseline(), 10**19, CP_A, 5)
    b = score_transaction(make_baseline(), 10**19, CP_A, 5)
    assert a.score == b.score
    assert a.contributing_factors == b.contributing_factors


def test_is_anomalous_threshold():
    normal = score_transaction(make_baseline(), 500 * 10**18, CP_A, 3)
    extreme = score_transaction(
        make_baseline(std_value_wei=1, mean_value_wei=100),
        value_wei=100_000 * 10**18,  # |z| astronomically large -> value_outlier ~100
        to_address=CP_B,
        recent_tx_count=200,  # 50x daily frequency spike
        is_new_counterparty=True,
    )
    assert normal.is_anomalous is False
    assert extreme.is_anomalous is True


def test_aggregate_pure():
    from at_shared.models import Transaction
    from at_shared.uuid7 import uuid7

    txs = [
        Transaction(id=uuid7(), agent_id="a", org_id="o", chain_id="base",
                    from_address=CP_A, to_address=CP_A, value_wei=10**18,
                    raw_params={}, decision="approve"),
        Transaction(id=uuid7(), agent_id="a", org_id="o", chain_id="base",
                    from_address=CP_A, to_address=CP_A, value_wei=2 * 10**18,
                    raw_params={}, decision="approve"),
        Transaction(id=uuid7(), agent_id="a", org_id="o", chain_id="base",
                    from_address=CP_A, to_address=CP_B, value_wei=3 * 10**18,
                    raw_params={}, decision="approve"),
    ]
    features = aggregate(txs)
    assert features.tx_count == 3
    assert features.total_volume_wei == 6 * 10**18
    assert features.unique_counterparties == 2
    assert features.top_counterparty_share == 2 / 3
    assert features.median_value_wei == 2 * 10**18