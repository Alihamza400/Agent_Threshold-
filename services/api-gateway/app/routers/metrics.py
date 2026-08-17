"""Real-time metrics for the dashboard (Phase 7.6, NFR Section 9).

Aggregations are computed server-side over the transactions/approvals tables so
the SPA stays thin and the heavy lifting is done once per poll. Percentiles use
Postgres `percentile_cont` — exact, not sampled.

Rate limits / quota: this endpoint is auditor-and-above, org-scoped, and runs
aggregate-only queries (no row scanning beyond the daily series).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.deps import require_auditor_or_above
from at_shared.db import get_db
from at_shared.models import Approval, Transaction
from at_shared.schemas.auth import CurrentUser
from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

router = APIRouter(prefix="/v1/metrics", tags=["metrics"])


def _bucket_count(db: Session, org_id: str, window_days: int) -> dict[str, int]:
    """Per-day transaction counts for the window, zero-filled for missing days."""
    since = datetime.now(UTC) - timedelta(days=window_days)
    day = func.date(Transaction.created_at)
    rows = db.execute(
        select(day.label("d"), func.count().label("n"))
        .where(Transaction.org_id == org_id, Transaction.created_at >= since)
        .group_by(day)
        .order_by(day)
    ).all()
    counts = {str(r.d): int(r.n) for r in rows}
    today = datetime.now(UTC).date()
    return {
        str(today - timedelta(days=i)): counts.get(str(today - timedelta(days=i)), 0)
        for i in range(window_days - 1, -1, -1)
    }


@router.get("/overview")
def metrics_overview(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_auditor_or_above),
) -> dict:
    now = datetime.now(UTC)
    since = now - timedelta(hours=24)
    org = user.org_id

    # --- totals + decision mix (24h) ---
    base = select(Transaction).where(Transaction.org_id == org, Transaction.created_at >= since)
    total_24h = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    mix = dict(
        db.execute(
            select(Transaction.decision, func.count())
            .where(Transaction.org_id == org, Transaction.created_at >= since)
            .group_by(Transaction.decision)
        ).all()
    )
    approve = mix.get("approve", 0)
    reject = mix.get("reject", 0)
    escalate = mix.get("escalate", 0)

    # --- fail-closed rate: decisions that did NOT auto-approve ---
    decided = approve + reject + escalate
    fail_closed_rate = round((reject + escalate) / decided, 4) if decided else 0.0

    # --- screening latency p50/p95 (24h, from screened_ms) ---
    latency_stmt = select(Transaction.screened_ms).where(
        Transaction.org_id == org,
        Transaction.created_at >= since,
        Transaction.screened_ms.is_not(None),
    )
    p50 = db.scalar(select(func.percentile_cont(0.5).within_group(latency_stmt.subquery().c.screened_ms)))
    p95 = db.scalar(select(func.percentile_cont(0.95).within_group(latency_stmt.subquery().c.screened_ms)))

    # --- daily series (14 days) ---
    series = _bucket_count(db, org, 14)

    # --- approval queue health ---
    pending_approvals = db.scalar(
        select(func.count())
        .select_from(Approval)
        .where(Approval.org_id == org, Approval.status == "pending")
    ) or 0
    resolved = db.scalar(
        select(func.count())
        .select_from(Approval)
        .where(
            Approval.org_id == org,
            Approval.status.in_(("approved", "rejected")),
            Approval.decided_at.is_not(None),
        )
    ) or 0
    avg_decision_hours = None
    if resolved:
        avg_seconds = db.scalar(
            select(func.avg(func.extract("epoch", Approval.decided_at - Approval.created_at)))
            .select_from(Approval)
            .where(
                Approval.org_id == org,
                Approval.status.in_(("approved", "rejected")),
                Approval.decided_at.is_not(None),
            )
        )
        if avg_seconds is not None:
            avg_decision_hours = round(float(avg_seconds) / 3600.0, 2)

    return {
        "window_hours": 24,
        "total_transactions_24h": total_24h,
        "decision_mix": {"approve": approve, "reject": reject, "escalate": escalate},
        "fail_closed_rate": fail_closed_rate,
        "latency_ms": {
            "p50": round(float(p50), 1) if p50 is not None else None,
            "p95": round(float(p95), 1) if p95 is not None else None,
        },
        "daily_series": {"days": list(series.keys()), "counts": list(series.values())},
        "approvals": {
            "pending": pending_approvals,
            "resolved_24h": resolved,
            "avg_decision_hours": avg_decision_hours,
        },
    }