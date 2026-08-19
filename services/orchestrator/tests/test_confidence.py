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
