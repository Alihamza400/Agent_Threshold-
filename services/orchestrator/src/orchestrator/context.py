"""Runtime context for policy evaluation: rolling counters from DB.

Builds an EngineContext with:
  - daily spend used (rolling 24h, USD-normalized from screened history)
  - recent tx count in the rate window
  - known counterparties (last 90 days)

Plus an AnomalyResult (FR-AI-02) computed against the agent's rolling
baseline. Fail-closed: DB errors raise, so the orchestrator rejects the
request rather than screening without complete context.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from anomaly_scorer.baseline import BaselineFeatures
from anomaly_scorer.scorer import AnomalyResult, score_transaction
from at_shared.models import Transaction
from policy_engine.engine import EngineContext
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from orchestrator.baseline import get_or_compute_baseline


def _now() -> datetime:
    return datetime.now(UTC)


class ScreeningContext:
    """Aggregated runtime context for a single screening request."""

    def __init__(
        self,
        engine_ctx: EngineContext,
        anomaly: AnomalyResult | None,
        baseline: BaselineFeatures | None,
        is_new_counterparty: bool,
    ):
        self.engine_ctx = engine_ctx
        self.anomaly = anomaly
        self.baseline = baseline
        self.is_new_counterparty = is_new_counterparty

    @property
    def anomaly_score(self) -> float:
        return self.anomaly.score if self.anomaly else 0.0


def build_screening_context(
    db: Session,
    agent_id: str,
    to_address: str | None,
    value_wei: int,
    usd_value: float | None = None,
) -> ScreeningContext:
    """Compute rolling behavioral inputs + anomaly score for the request."""
    now = _now()
    day_ago = now - timedelta(days=1)
    window_minutes = now - timedelta(minutes=1)
    baseline_start = now - timedelta(days=90)

    daily_used = (
        db.scalar(
            select(func.coalesce(func.sum(Transaction.usd_value), 0.0)).where(
                Transaction.agent_id == agent_id,
                Transaction.created_at >= day_ago,
                Transaction.decision.in_(["approve", "confirmed"]),
                Transaction.usd_value.isnot(None),
            )
        )
        or 0.0
    )

    recent_count = (
        db.scalar(
            select(func.count(Transaction.id)).where(
                Transaction.agent_id == agent_id,
                Transaction.created_at >= window_minutes,
            )
        )
        or 0
    )

    known_rows = db.execute(
        select(Transaction.to_address)
        .where(
            Transaction.agent_id == agent_id,
            Transaction.created_at >= baseline_start,
            Transaction.to_address.isnot(None),
        )
        .distinct()
    ).scalars()
    known = frozenset(addr.lower() for addr in known_rows)

    to = to_address.lower() if to_address else None
    is_new = to is not None and to not in known

    baseline = get_or_compute_baseline(db, agent_id)

    anomaly: AnomalyResult | None = None
    if baseline is not None:
        anomaly = score_transaction(
            baseline,
            value_wei=value_wei,
            to_address=to_address,
            recent_tx_count=int(recent_count),
            is_new_counterparty=is_new,
        )

    engine_ctx = EngineContext(
        usd_value=usd_value,
        daily_spend_used_usd=float(daily_used),
        recent_tx_count=int(recent_count),
        known_counterparties=known,
        anomaly_score=anomaly.score if anomaly else None,
        now_utc_minute=now.hour * 60 + now.minute,
        fail_closed=True,
    )
    return ScreeningContext(engine_ctx, anomaly, baseline, is_new)
