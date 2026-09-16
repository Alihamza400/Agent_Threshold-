"""Aggregate confidence math (8.3)."""

from __future__ import annotations

from orchestrator.confidence import aggregate_confidence
from screening_agents.schemas import RiskLevel


def test_no_signals_is_full_confidence():
    assert aggregate_confidence() == 100.0


def test_classifier_low_halves():
    assert aggregate_confidence(classifier_conf=0.0) == 50.0
    assert aggregate_confidence(classifier_conf=0.5) == 75.0
    assert aggregate_confidence(classifier_conf=1.0) == 100.0


def test_classifier_clamped():
    assert aggregate_confidence(classifier_conf=-1.0) == 50.0
    assert aggregate_confidence(classifier_conf=5.0) == 100.0


def test_anomaly_collapses_confidence():
    assert aggregate_confidence(anomaly_score=100.0) == 0.0
    assert aggregate_confidence(anomaly_score=50.0) == 50.0
    assert aggregate_confidence(anomaly_score=0.0) == 100.0


def test_risk_level_multipliers():
    assert aggregate_confidence(risk_level=RiskLevel.LOW) == 100.0
    assert aggregate_confidence(risk_level=RiskLevel.MEDIUM) == 85.0
    assert aggregate_confidence(risk_level=RiskLevel.HIGH) == 60.0
    assert aggregate_confidence(risk_level=RiskLevel.CRITICAL) == 30.0


def test_balance_drain_is_zero():
    assert aggregate_confidence(balance_drain=True) == 0.0
    assert (
        aggregate_confidence(classifier_conf=1.0, risk_level=RiskLevel.LOW, balance_drain=True)
        == 0.0
    )


def test_signals_combine_multiplicatively():
    # 100 * 0.925 (classifier 0.85) * (1 - 0.20) (anomaly 20) * 0.85 (medium) = 62.90
    assert (
        aggregate_confidence(classifier_conf=0.85, anomaly_score=20.0, risk_level=RiskLevel.MEDIUM)
        == 62.9
    )


def test_deterministic():
    args = dict(classifier_conf=0.8, anomaly_score=20.0, risk_level=RiskLevel.HIGH)
    assert aggregate_confidence(**args) == aggregate_confidence(**args)


def test_all_none_signals_returns_full_confidence():
    assert aggregate_confidence(
        classifier_conf=None, anomaly_score=None, risk_level=None, balance_drain=False
    ) == 100.0


def test_all_max_signals_collapses_to_zero():
    assert (
        aggregate_confidence(classifier_conf=1.0, anomaly_score=100.0, risk_level=RiskLevel.CRITICAL)
        == 0.0
    )


def test_anomaly_score_clamped_above_100():
    assert aggregate_confidence(anomaly_score=200.0) == 0.0
    assert aggregate_confidence(anomaly_score=150.0) == 0.0


def test_anomaly_score_clamped_below_zero():
    assert aggregate_confidence(anomaly_score=-50.0) == 100.0


def test_classifier_conf_zero_halves_confidence():
    # factor = 0.5 + 0.5 * 0.0 = 0.5
    assert aggregate_confidence(classifier_conf=0.0) == 50.0


def test_classifier_conf_one_keeps_full():
    # factor = 0.5 + 0.5 * 1.0 = 1.0
    assert aggregate_confidence(classifier_conf=1.0) == 100.0


def test_balance_drain_overrides_all_positive_signals():
    result = aggregate_confidence(
        classifier_conf=1.0,
        anomaly_score=0.0,
        risk_level=RiskLevel.LOW,
        balance_drain=True,
    )
    assert result == 0.0


def test_unknown_risk_level_uses_default_factor():
    # _RISK_LEVEL_FACTOR.get(risk_level, 0.5) -> unknown uses 0.5
    result = aggregate_confidence(risk_level="bogus")  # type: ignore[arg-type]
    assert result == 50.0


def test_anomaly_at_boundary_exactly_50():
    # 100 * (1 - 0.5) = 50.0
    assert aggregate_confidence(anomaly_score=50.0) == 50.0


def test_anomaly_at_boundary_exactly_0():
    assert aggregate_confidence(anomaly_score=0.0) == 100.0


def test_anomaly_at_boundary_exactly_100():
    assert aggregate_confidence(anomaly_score=100.0) == 0.0


def test_classifier_at_midpoint():
    # factor = 0.5 + 0.5 * 0.5 = 0.75
    assert aggregate_confidence(classifier_conf=0.5) == 75.0


def test_two_signals_multiplicative():
    # classifier 0.5 -> factor 0.75; anomaly 50 -> factor 0.5; 100 * 0.75 * 0.5 = 37.5
    assert aggregate_confidence(classifier_conf=0.5, anomaly_score=50.0) == 37.5


def test_three_signals_multiplicative():
    # classifier 0.8 -> 0.9; anomaly 20 -> 0.8; risk MEDIUM -> 0.85
    # 100 * 0.9 * 0.8 * 0.85 = 61.2
    assert (
        aggregate_confidence(classifier_conf=0.8, anomaly_score=20.0, risk_level=RiskLevel.MEDIUM)
        == 61.2
    )


def test_balance_drain_true_with_no_other_signals():
    assert aggregate_confidence(balance_drain=True) == 0.0


def test_risk_level_critical_reduces_to_30_percent():
    assert aggregate_confidence(risk_level=RiskLevel.CRITICAL) == 30.0


def test_risk_level_high_reduces_to_60_percent():
    assert aggregate_confidence(risk_level=RiskLevel.HIGH) == 60.0


def test_risk_level_medium_reduces_to_85_percent():
    assert aggregate_confidence(risk_level=RiskLevel.MEDIUM) == 85.0


def test_risk_level_low_keeps_100_percent():
    assert aggregate_confidence(risk_level=RiskLevel.LOW) == 100.0


def test_classifier_very_low():
    # factor = 0.5 + 0.5 * 0.01 = 0.505
    result = aggregate_confidence(classifier_conf=0.01)
    assert result == 50.5


def test_anomaly_very_high():
    # 100 * (1 - 0.99) = 1.0
    assert aggregate_confidence(anomaly_score=99.0) == 1.0
