"""Runtime context for policy evaluation: rolling counters from DB.

Builds an EngineContext with:
  - daily spend used (rolling 24h, USD-normalized from screened history)
  - recent tx count in the rate window
  - known counterparties (last 90 days)

Fail-closed: DB errors raise, so the orchestrator rejects the request rather
than screening without complete context.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from at_shared.models import Transaction
from policy_engine.engine import EngineContext
from sqlalchemy import func, select
from sqlalchemy.orm import Session


def _now() -> datetime:
    return datetime.now(UTC)


def build_engine_context(
    db: Session,
    agent_id: str,
    usd_value: float | None = None,
    anomaly_score: float | None = None,
) -> EngineContext:
    """Compute rolling behavioral inputs for the policy engine."""
    now = _now()
    day_ago = now - timedelta(days=1)
    window_minutes = now - timedelta(minutes=1)
    baseline_start = now - timedelta(days=90)

    # Rolling 24h USD spend already used (approved/executed transactions).
    daily_used = db.scalar(
        select(func.coalesce(func.sum(Transaction.usd_value), 0.0)).where(
            Transaction.agent_id == agent_id,
            Transaction.created_at >= day_ago,
            Transaction.decision.in_(["approve", "confirmed"]),
            Transaction.usd_value.isnot(None),
        )
    ) or 0.0

    # Recent tx count in the rate window (any screened).
    recent_count = db.scalar(
        select(func.count(Transaction.id)).where(
            Transaction.agent_id == agent_id,
            Transaction.created_at >= window_minutes,
        )
    ) or 0

    # Known counterparties over the 90-day baseline.
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

    return EngineContext(
        usd_value=usd_value,
        daily_spend_used_usd=float(daily_used),
        recent_tx_count=int(recent_count),
        known_counterparties=known,
        anomaly_score=anomaly_score,
        now_utc_minute=now.hour * 60 + now.minute,
        fail_closed=True,
    )