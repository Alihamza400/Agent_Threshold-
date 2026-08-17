"""Baseline computation from transaction history.

Aggregates the rolling 90-day window into a reproducible BaselineProfile
(TRD FR-DATA-02: baseline updates within 5 minutes of a confirmed tx).

Pure computations; DB queries isolated in `compute_baseline`.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from at_shared.models import Transaction

WINDOW_DAYS = 90


@dataclass(frozen=True)
class BaselineFeatures:
    """Numerical feature vector used by the scorer."""

    tx_count: int
    total_volume_wei: int
    mean_value_wei: float
    median_value_wei: float
    std_value_wei: float
    avg_freq_per_day: float
    unique_counterparties: int
    top_counterparty_share: float  # fraction of txs to the single most-used counterparty
    unique_value_ratio: float      # distinct value magnitudes / tx_count (0 if none)


def aggregate(txs: Sequence[Transaction], window_days: int = WINDOW_DAYS) -> BaselineFeatures:
    """Compute baseline features from a sequence of transactions (pure)."""
    values = [t.value_wei for t in txs]
    n = len(values)

    if n == 0:
        return BaselineFeatures(
            tx_count=0,
            total_volume_wei=0,
            mean_value_wei=0.0,
            median_value_wei=0.0,
            std_value_wei=0.0,
            avg_freq_per_day=0.0,
            unique_counterparties=0,
            top_counterparty_share=0.0,
            unique_value_ratio=0.0,
        )

    counterparties = [t.to_address.lower() for t in txs if t.to_address]
    cp_freq: dict[str, int] = {}
    for cp in counterparties:
        cp_freq[cp] = cp_freq.get(cp, 0) + 1
    unique_cp = len(cp_freq)
    top_share = max(cp_freq.values()) / n if cp_freq else 0.0

    distinct_values = len(set(values))
    unique_value_ratio = distinct_values / n

    std = statistics.pstdev(values) if n > 1 else 0.0

    return BaselineFeatures(
        tx_count=n,
        total_volume_wei=sum(values),
        mean_value_wei=statistics.fmean(values),
        median_value_wei=float(statistics.median(values)),
        std_value_wei=float(std),
        avg_freq_per_day=n / window_days,
        unique_counterparties=unique_cp,
        top_counterparty_share=top_share,
        unique_value_ratio=unique_value_ratio,
    )


def to_features_dict(features: BaselineFeatures) -> dict:
    return {
        "tx_count": features.tx_count,
        "total_volume_wei": features.total_volume_wei,
        "mean_value_wei": features.mean_value_wei,
        "median_value_wei": features.median_value_wei,
        "std_value_wei": features.std_value_wei,
        "avg_freq_per_day": features.avg_freq_per_day,
        "unique_counterparties": features.unique_counterparties,
        "top_counterparty_share": features.top_counterparty_share,
        "unique_value_ratio": features.unique_value_ratio,
        "window_days": WINDOW_DAYS,
        "computed_at_utc": datetime.now(UTC).isoformat(),
    }


def from_features_dict(data: dict) -> BaselineFeatures:
    return BaselineFeatures(
        tx_count=int(data["tx_count"]),
        total_volume_wei=int(data["total_volume_wei"]),
        mean_value_wei=float(data["mean_value_wei"]),
        median_value_wei=float(data["median_value_wei"]),
        std_value_wei=float(data["std_value_wei"]),
        avg_freq_per_day=float(data["avg_freq_per_day"]),
        unique_counterparties=int(data["unique_counterparties"]),
        top_counterparty_share=float(data["top_counterparty_share"]),
        unique_value_ratio=float(data["unique_value_ratio"]),
    )


def baseline_window_start(now: datetime | None = None) -> datetime:
    now = now or datetime.now(UTC)
    return now - timedelta(days=WINDOW_DAYS)