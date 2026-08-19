"""Baseline profile service (FR-DATA-02).

Loads the agent's rolling 90-day baseline; if absent, computes it from
screened transaction history and persists it. Also refreshes the profile
after a transaction is confirmed so the Anomaly Scorer always reads a
current baseline.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from anomaly_scorer.baseline import (
    WINDOW_DAYS,
    BaselineFeatures,
    aggregate,
    baseline_window_start,
    from_features_dict,
    to_features_dict,
)
from at_shared.models import BaselineProfile, Transaction
from at_shared.uuid7 import uuid7
from sqlalchemy import select
from sqlalchemy.orm import Session


def get_or_compute_baseline(db: Session, agent_id: str) -> BaselineFeatures | None:
    """Return baseline features; compute+persist on first use or stale."""
    profile = db.scalar(
        select(BaselineProfile)
        .where(BaselineProfile.agent_id == agent_id)
        .order_by(BaselineProfile.computed_at.desc())
        .limit(1)
    )

    # refresh if profile is older than the window (or missing)
    need_refresh = profile is None or (
        profile.computed_at.replace(tzinfo=UTC)
        if profile.computed_at.tzinfo is None
        else profile.computed_at
    ) < datetime.now(UTC) - timedelta(days=WINDOW_DAYS // 3)

    if need_refresh:
        txs = db.scalars(
            select(Transaction).where(
                Transaction.agent_id == agent_id,
                Transaction.created_at >= baseline_window_start(),
            )
        ).all()
        features = aggregate(txs)
        if profile is None:
            profile = BaselineProfile(
                id=uuid7(), agent_id=agent_id, window_days=WINDOW_DAYS, features={}
            )
            db.add(profile)
        profile.tx_count = features.tx_count
        profile.total_volume_wei = features.total_volume_wei
        profile.mean_value_wei = features.mean_value_wei
        profile.median_value_wei = features.median_value_wei
        profile.std_value_wei = features.std_value_wei
        profile.avg_freq_per_day = features.avg_freq_per_day
        profile.unique_counterparties = features.unique_counterparties
        profile.features = to_features_dict(features)
        profile.computed_at = datetime.now(UTC)
        db.commit()
        return features

    return from_features_dict(profile.features)


def refresh_baseline(db: Session, agent_id: str) -> None:
    """Recompute the baseline after a confirmed tx (FR-DATA-02).

    Throttled to a 5-minute cadence so the hot path never pays a full
    aggregation per request; the profile stays within the 5-minute freshness
    budget required by the TRD.
    """
    now = datetime.now(UTC)
    profile = db.scalar(
        select(BaselineProfile)
        .where(BaselineProfile.agent_id == agent_id)
        .order_by(BaselineProfile.computed_at.desc())
        .limit(1)
    )
    if profile is not None:
        last = profile.computed_at
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        if now - last < timedelta(minutes=5):
            return  # fresh enough; skip aggregation on the hot path

    txs = db.scalars(
        select(Transaction).where(
            Transaction.agent_id == agent_id,
            Transaction.created_at >= baseline_window_start(),
        )
    ).all()
    features = aggregate(txs)
    if profile is None:
        profile = BaselineProfile(
            id=uuid7(), agent_id=agent_id, window_days=WINDOW_DAYS, features={}
        )
        db.add(profile)
    profile.tx_count = features.tx_count
    profile.total_volume_wei = features.total_volume_wei
    profile.mean_value_wei = features.mean_value_wei
    profile.median_value_wei = features.median_value_wei
    profile.std_value_wei = features.std_value_wei
    profile.avg_freq_per_day = features.avg_freq_per_day
    profile.unique_counterparties = features.unique_counterparties
    profile.features = to_features_dict(features)
    profile.computed_at = datetime.now(UTC)
    db.commit()
