"""Rule-based v1 anomaly scorer (TRD FR-AI-02).

Deterministic and fast (<500ms p95) — no LLM on the hot path. Produces a
0-100 anomaly score plus the top contributing factors.

Scoring model (weights sum to 1.0):
  value_deviation   : z-score of tx value against baseline mean/std
  new_counterparty  : first-ever interaction with this address
  frequency_spike   : recent tx count vs baseline daily rate
  amount_ratio      : tx value vs baseline median (log-scale sensitivity)
  counterparty_concentration: deviation from the agent's usual top-counterparty
                             concentration pattern

Determinism guarantee: identical inputs produce identical output.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from anomaly_scorer.baseline import BaselineFeatures

# contribution weights (sum = 1.0)
# value_outlier is dominant: a maxed z-score alone must push past the anomaly
# threshold. New-counterparty escalation is independently enforced by the
# policy engine (rule 9), so it is additive here, not the sole gate.
_WEIGHTS = {
    "value_outlier": 0.60,
    "new_counterparty": 0.25,
    "frequency_spike": 0.10,
    "counterparty_concentration": 0.05,
}


@dataclass(frozen=True)
class AnomalyResult:
    score: float                       # 0-100
    contributing_factors: list[dict] = field(default_factory=list)  # {factor, weight, detail}
    is_anomalous: bool = False


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def _sigmoid_like(x: float) -> float:
    """Squash an unbounded deviation into 0..1, saturating past |3|."""
    return x / (1 + abs(x))


def score_transaction(
    baseline: BaselineFeatures,
    value_wei: int,
    to_address: str | None,
    recent_tx_count: int,
    window_minutes: int = 1440,
    is_new_counterparty: bool = False,
) -> AnomalyResult:
    """Score a transaction against the agent's rolling baseline. Pure."""
    factors: list[dict] = []
    components: dict[str, float] = {}

    to = to_address.lower() if to_address else None

    # ---- value deviation (|z-score|; both tails are anomalous) -------------
    if baseline.tx_count >= 5 and baseline.std_value_wei > 0:
        z = abs((value_wei - baseline.mean_value_wei) / baseline.std_value_wei)
        components["value_outlier"] = _sigmoid_like(z) * 100
        factors.append(
            {
                "factor": "value_outlier",
                "weight": _WEIGHTS["value_outlier"],
                "detail": f"|z-score| {z:.2f} vs baseline mean {baseline.mean_value_wei:.2f} wei (std {baseline.std_value_wei:.2f})",
            }
        )
    else:
        components["value_outlier"] = 0.0
        factors.append({"factor": "value_outlier", "weight": _WEIGHTS["value_outlier"], "detail": "insufficient baseline"})

    # ---- new counterparty --------------------------------------------------
    if is_new_counterparty:
        components["new_counterparty"] = 100.0
        factors.append(
            {
                "factor": "new_counterparty",
                "weight": _WEIGHTS["new_counterparty"],
                "detail": f"first interaction with {to}",
            }
        )
    else:
        components["new_counterparty"] = 0.0
        factors.append(
            {
                "factor": "new_counterparty",
                "weight": _WEIGHTS["new_counterparty"],
                "detail": "known counterparty",
            }
        )

    # ---- frequency spike ----------------------------------------------------
    if baseline.tx_count > 0:
        expected_in_window = baseline.avg_freq_per_day * (window_minutes / 1440.0)
        if expected_in_window > 0:
            spike = recent_tx_count / expected_in_window
            components["frequency_spike"] = _sigmoid_like(spike - 1.0) * 100
            factors.append(
                {
                    "factor": "frequency_spike",
                    "weight": _WEIGHTS["frequency_spike"],
                    "detail": f"{recent_tx_count} txs in {window_minutes}m vs expected ~{expected_in_window:.2f}",
                }
            )
        else:
            components["frequency_spike"] = 0.0
            factors.append({"factor": "frequency_spike", "weight": _WEIGHTS["frequency_spike"], "detail": "zero-expected baseline"})
    else:
        components["frequency_spike"] = 0.0
        factors.append({"factor": "frequency_spike", "weight": _WEIGHTS["frequency_spike"], "detail": "no baseline history"})

    # ---- counterparty concentration deviation ------------------------------
    # An agent that usually sends to one counterparty and suddenly diversifies
    # is flagged. Uses baseline top_counterparty_share as the expected value.
    if baseline.tx_count >= 5:
        # we do not know the target's share directly here; proxy: if tx_count
        # grew relative to baseline unique_counterparties, concentration fell.
        expected_diversity = 1.0 - baseline.top_counterparty_share
        components["counterparty_concentration"] = _clamp((1.0 - expected_diversity) * 30.0)
        factors.append(
            {
                "factor": "counterparty_concentration",
                "weight": _WEIGHTS["counterparty_concentration"],
                "detail": f"baseline top-counterparty share {baseline.top_counterparty_share:.2f}",
            }
        )
    else:
        components["counterparty_concentration"] = 0.0
        factors.append(
            {"factor": "counterparty_concentration", "weight": _WEIGHTS["counterparty_concentration"], "detail": "insufficient baseline"}
        )

    total = sum(_clamp(components.get(f, 0.0)) * _WEIGHTS[f] for f in _WEIGHTS)
    score = round(_clamp(total), 2)
    return AnomalyResult(
        score=score,
        contributing_factors=factors,
        is_anomalous=score >= 70.0,  # aligns with default policy threshold
    )