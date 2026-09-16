"""Anomaly Scorer unit tests — determinism + sensitivity (FR-AI-02)."""

from __future__ import annotations

from anomaly_scorer.baseline import BaselineFeatures, aggregate
from anomaly_scorer.scorer import score_transaction

CP_A = "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
CP_B = "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
CP_C = "0xcccccccccccccccccccccccccccccccccccccccc"


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


def test_single_data_point_baseline():
    baseline = BaselineFeatures(
        tx_count=1, total_volume_wei=100 * 10**18,
        mean_value_wei=100 * 10**18, median_value_wei=100 * 10**18,
        std_value_wei=0.0, avg_freq_per_day=0.007,
        unique_counterparties=1, top_counterparty_share=1.0,
        unique_value_ratio=1.0,
    )
    result = score_transaction(baseline, value_wei=100 * 10**18, to_address=CP_A, recent_tx_count=1)
    assert result.score >= 0.0
    assert isinstance(result.score, float)
    factors = {f["factor"]: f for f in result.contributing_factors}
    assert "insufficient baseline" in factors["value_outlier"]["detail"]


def test_baseline_tx_count_below_5_skips_z_score():
    baseline = BaselineFeatures(
        tx_count=4, total_volume_wei=400 * 10**18,
        mean_value_wei=100 * 10**18, median_value_wei=100 * 10**18,
        std_value_wei=50 * 10**18, avg_freq_per_day=0.03,
        unique_counterparties=2, top_counterparty_share=0.5,
        unique_value_ratio=0.75,
    )
    result = score_transaction(baseline, value_wei=10_000 * 10**18, to_address=CP_A, recent_tx_count=1)
    factors = {f["factor"]: f for f in result.contributing_factors}
    assert "insufficient baseline" in factors["value_outlier"]["detail"]


def test_extreme_frequency_spike():
    baseline = make_baseline(avg_freq_per_day=0.01, tx_count=100)
    normal = score_transaction(baseline, value_wei=500 * 10**18, to_address=CP_A, recent_tx_count=0)
    spike = score_transaction(baseline, value_wei=500 * 10**18, to_address=CP_A, recent_tx_count=500)
    assert spike.score > normal.score
    factors = {f["factor"]: f for f in spike.contributing_factors}
    assert "frequency_spike" in factors


def test_all_known_counterparties_no_new_cp_factor():
    result = score_transaction(make_baseline(), value_wei=500 * 10**18, to_address=CP_A, recent_tx_count=3, is_new_counterparty=False)
    factors = {f["factor"]: f for f in result.contributing_factors}
    assert "known counterparty" in factors["new_counterparty"]["detail"]


def test_zero_value_transaction():
    result = score_transaction(make_baseline(), value_wei=0, to_address=CP_A, recent_tx_count=3)
    assert result.score >= 0.0
    assert isinstance(result.score, float)


def test_value_below_mean():
    baseline = make_baseline(mean_value_wei=1000 * 10**18, std_value_wei=200 * 10**18)
    result = score_transaction(baseline, value_wei=100 * 10**18, to_address=CP_A, recent_tx_count=3)
    factors = {f["factor"]: f for f in result.contributing_factors}
    assert "value_outlier" in factors
    assert "z-score" in factors["value_outlier"]["detail"] or "insufficient" in factors["value_outlier"]["detail"]


def test_value_above_mean():
    baseline = make_baseline(mean_value_wei=1000 * 10**18, std_value_wei=200 * 10**18)
    result = score_transaction(baseline, value_wei=5000 * 10**18, to_address=CP_A, recent_tx_count=3)
    factors = {f["factor"]: f for f in result.contributing_factors}
    assert "value_outlier" in factors


def test_score_range_0_to_100():
    result = score_transaction(make_baseline(), value_wei=500 * 10**18, to_address=CP_A, recent_tx_count=3)
    assert 0.0 <= result.score <= 100.0


def test_score_extreme_still_clamped():
    result = score_transaction(
        make_baseline(std_value_wei=1, mean_value_wei=100),
        value_wei=1_000_000 * 10**18,
        to_address=CP_B,
        recent_tx_count=10_000,
        is_new_counterparty=True,
    )
    assert result.score <= 100.0
    assert result.is_anomalous is True


def test_to_address_none():
    result = score_transaction(make_baseline(), value_wei=500 * 10**18, to_address=None, recent_tx_count=3)
    assert result.score >= 0.0


def test_counterparty_concentration_factor():
    # High top_counterparty_share means low diversity -> concentration factor is higher
    high_conc = make_baseline(top_counterparty_share=0.95, tx_count=100)
    low_conc = make_baseline(top_counterparty_share=0.2, tx_count=100)
    r_high = score_transaction(high_conc, value_wei=500 * 10**18, to_address=CP_A, recent_tx_count=3)
    r_low = score_transaction(low_conc, value_wei=500 * 10**18, to_address=CP_A, recent_tx_count=3)
    assert r_high.score >= r_low.score


def test_aggregate_empty_list():
    features = aggregate([])
    assert features.tx_count == 0
    assert features.total_volume_wei == 0
    assert features.unique_counterparties == 0


def test_aggregate_single_tx():
    from at_shared.models import Transaction
    from at_shared.uuid7 import uuid7

    txs = [
        Transaction(id=uuid7(), agent_id="a", org_id="o", chain_id="base",
                    from_address=CP_A, to_address=CP_B, value_wei=10**18,
                    raw_params={}, decision="approve"),
    ]
    features = aggregate(txs)
    assert features.tx_count == 1
    assert features.total_volume_wei == 10**18
    assert features.unique_counterparties == 1
    assert features.top_counterparty_share == 1.0
    assert features.std_value_wei == 0.0


def test_aggregate_same_counterparty():
    from at_shared.models import Transaction
    from at_shared.uuid7 import uuid7

    txs = [
        Transaction(id=uuid7(), agent_id="a", org_id="o", chain_id="base",
                    from_address=CP_A, to_address=CP_B, value_wei=10**18,
                    raw_params={}, decision="approve"),
        Transaction(id=uuid7(), agent_id="a", org_id="o", chain_id="base",
                    from_address=CP_A, to_address=CP_B, value_wei=2 * 10**18,
                    raw_params={}, decision="approve"),
    ]
    features = aggregate(txs)
    assert features.unique_counterparties == 1
    assert features.top_counterparty_share == 1.0


def test_frequency_spike_zero_expected_baseline():
    baseline = make_baseline(avg_freq_per_day=0.0, tx_count=200)
    result = score_transaction(baseline, value_wei=500 * 10**18, to_address=CP_A, recent_tx_count=10)
    factors = {f["factor"]: f for f in result.contributing_factors}
    assert "zero-expected" in factors["frequency_spike"]["detail"]


def test_frequency_spike_no_baseline_history():
    baseline = make_baseline(tx_count=0)
    result = score_transaction(baseline, value_wei=500 * 10**18, to_address=CP_A, recent_tx_count=10)
    factors = {f["factor"]: f for f in result.contributing_factors}
    assert "no baseline history" in factors["frequency_spike"]["detail"]


def test_baseline_features_to_from_dict_roundtrip():
    original = make_baseline()
    from anomaly_scorer.baseline import from_features_dict, to_features_dict

    d = to_features_dict(original)
    restored = from_features_dict(d)
    assert restored.tx_count == original.tx_count
    assert restored.total_volume_wei == original.total_volume_wei
    assert restored.mean_value_wei == original.mean_value_wei
    assert restored.median_value_wei == original.median_value_wei
    assert restored.std_value_wei == original.std_value_wei
    assert restored.avg_freq_per_day == original.avg_freq_per_day
    assert restored.unique_counterparties == original.unique_counterparties
    assert restored.top_counterparty_share == original.top_counterparty_share
    assert restored.unique_value_ratio == original.unique_value_ratio


def test_contributing_factors_have_required_keys():
    result = score_transaction(make_baseline(), value_wei=500 * 10**18, to_address=CP_A, recent_tx_count=3)
    for factor in result.contributing_factors:
        assert "factor" in factor
        assert "weight" in factor
        assert "detail" in factor
