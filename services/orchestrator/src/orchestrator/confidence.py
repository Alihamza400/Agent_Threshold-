"""Aggregate confidence + escalate-threshold logic (8.3).

The deterministic policy engine decides APPROVE / REJECT / ESCALATE on its
own. Advisory signals (intent classifier confidence, anomaly score, simulated
risk) are folded into a single 0-100 aggregate confidence; an APPROVE is
downgraded to ESCALATE when confidence drops below the configured threshold
or a fail-closed gate (simulation error, balance drain) trips.

The function is pure and deterministic — identical inputs always yield the
same confidence.
"""

from __future__ import annotations

from screening_agents.schemas import RiskLevel

# Multiplier applied per simulated risk level. CRITICAL collapses confidence
# toward 0 so the transaction is almost always escalated for human review.
_RISK_LEVEL_FACTOR: dict[RiskLevel, float] = {
    RiskLevel.LOW: 1.0,
    RiskLevel.MEDIUM: 0.85,
    RiskLevel.HIGH: 0.6,
    RiskLevel.CRITICAL: 0.3,
}


def aggregate_confidence(
    *,
    classifier_conf: float | None = None,
    anomaly_score: float | None = None,
    risk_level: RiskLevel | None = None,
    balance_drain: bool = False,
) -> float:
    """Combine advisory signals into a 0-100 aggregate confidence.

    Args:
        classifier_conf: intent classifier confidence (0..1), advisory.
        anomaly_score: rule-based anomaly score (0..100), advisory.
        risk_level: simulation interpreter risk level, advisory.
        balance_drain: interpreter flagged a balance-drain pattern.

    A confirmed balance drain returns 0.0 regardless of the other signals so
    the pipeline always escalates (fail-closed, FR-AI-03).
    """
    confidence = 100.0

    if classifier_conf is not None:
        # 0..1 -> factor 0.5..1.0: a low-agreement classification halves confidence
        confidence *= 0.5 + 0.5 * min(max(classifier_conf, 0.0), 1.0)

    if anomaly_score is not None:
        # high anomaly -> confidence collapses toward zero
        confidence *= max(0.0, 1.0 - min(max(anomaly_score, 0.0), 100.0) / 100.0)

    if risk_level is not None:
        confidence *= _RISK_LEVEL_FACTOR.get(risk_level, 0.5)

    if balance_drain:
        return 0.0

    return round(confidence, 2)
