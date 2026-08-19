"""Fail-closed escalation expiry (task 8.4).

Unresolved escalations expire after `escalation_ttl_minutes` and default to
REJECT. This is the fail-closed guarantee for human-in-the-loop: if no one
acts, the transaction is never auto-executed.

The worker runs expiry proactively so the transition happens even when nobody
reads the queue (the gateway also expires lazily on read as a belt-and-braces
defense).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime

from at_shared.models import Approval, Transaction
from sqlalchemy import select
from sqlalchemy.orm import Session

logger = logging.getLogger("notification_service.expire")


def expire_overdue(session_factory: Callable[[], Session], *, ttl_minutes: int) -> int:
    """Transition overdue pending escalations to expired (default reject).

    Returns the number of escalations expired. Transactionally atomic: the
    approval status and the underlying transaction status flip together, so
    the default-reject is never half-applied.
    """
    now = datetime.now(UTC)
    try:
        with session_factory() as session:
            overdue = session.scalars(
                select(Approval)
                .where(
                    Approval.status == "pending",
                    Approval.expires_at.is_not(None),
                    Approval.expires_at < now,
                )
                .limit(500)
            ).all()
            for approval in overdue:
                approval.status = "expired"
                tx = session.get(Transaction, approval.transaction_id)
                if tx is not None:
                    tx.status = "rejected"
            if overdue:
                session.commit()
                logger.info("expired %s overdue escalation(s)", len(overdue))
            return len(overdue)
    except Exception:  # noqa: BLE001 - expiry must not kill the worker loop
        logger.exception("expiry sweep failed")
        return 0
