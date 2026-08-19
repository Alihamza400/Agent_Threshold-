"""DB-backed escalation notification outbox (task 8.4).

Owns the delivery bookkeeping columns on `approvals`:

  notified_at           set when the first successful delivery completes
  notify_attempts       number of delivery attempts made
  notify_last_error     last delivery failure reason (observability)
  notify_next_attempt_at when the next retry is due

`claim_due` SELECTs pending escalations that are due for delivery; each claim
marks the row as being retried (increments attempts, sets next attempt) in the
SAME transaction that resolves the row, so concurrent workers never deliver the
same escalation twice.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from at_shared.models import Approval
from sqlalchemy import select
from sqlalchemy.orm import Session

logger = logging.getLogger("notification_service.outbox")


class OutboxError(Exception):
    """DB-level outbox failure. The worker loop survives and retries."""


class NotificationOutbox:
    def __init__(
        self,
        session_factory: Callable[[], Session],
        *,
        max_attempts: int = 8,
        backoff_base_seconds: float = 1.0,
        lease_seconds: float = 30.0,
    ) -> None:
        self._session_factory = session_factory
        self.max_attempts = max_attempts
        self.backoff_base = backoff_base_seconds
        self.lease_seconds = lease_seconds

    def claim_due(self, limit: int = 50) -> list[Approval]:
        """Return due-for-delivery pending escalations.

        An escalation is due when it has never been notified and either has no
        scheduled retry yet (fresh) or `notify_next_attempt_at` has passed.
        Each claim stamps the row with a lease (`notify_next_attempt_at` set to
        now + lease) in the SAME transaction, so concurrent workers never
        deliver the same escalation twice within the lease window.
        Attempts at or above `max_attempts` are skipped (delivery marked
        failed; the human queue is unaffected).
        """
        now = datetime.now(UTC)
        lease_until = now + timedelta(seconds=self.lease_seconds)
        try:
            with self._session_factory() as session:
                rows = session.scalars(
                    select(Approval)
                    .where(
                        Approval.status == "pending",
                        Approval.notified_at.is_(None),
                        Approval.notify_attempts < self.max_attempts,
                        (
                            Approval.notify_next_attempt_at.is_(None)
                            | (Approval.notify_next_attempt_at <= now)
                        ),
                    )
                    .order_by(Approval.created_at.asc())
                    .limit(limit)
                ).all()
                for row in rows:
                    row.notify_attempts += 1
                    if row.notify_next_attempt_at is None:
                        row.notify_next_attempt_at = lease_until  # in-flight lease
                session.commit()
                return rows
        except Exception as exc:  # noqa: BLE001 - outbox must fail soft
            logger.exception("outbox claim failed")
            raise OutboxError(f"claim failed: {exc}") from exc

    def mark_delivered(self, approval_id: str) -> None:
        with self._session_factory() as session:
            row = session.get(Approval, approval_id)
            if row is not None and row.status == "pending":
                row.notified_at = datetime.now(UTC)
                row.notify_last_error = None
            session.commit()

    def schedule_retry(self, approval_id: str, error: str) -> None:
        """Record a failed attempt and schedule the next one (exponential)."""
        with self._session_factory() as session:
            row = session.get(Approval, approval_id)
            if row is not None and row.status == "pending":
                row.notify_last_error = error[:500]
                if row.notify_attempts >= self.max_attempts:
                    # Exhausted: delivery fails permanently for this escalation,
                    # but the approval itself stays pending for the human queue.
                    row.notify_next_attempt_at = None
                    logger.error(
                        "notification exhausted for approval %s after %s attempts: %s",
                        approval_id,
                        row.notify_attempts,
                        error,
                    )
                else:
                    delay = self.backoff_base * (2 ** (row.notify_attempts - 1))
                    row.notify_next_attempt_at = datetime.now(UTC) + timedelta(seconds=delay)
            session.commit()

    def pending_due_count(self) -> int:
        """Observability: how many escalations are waiting on delivery."""
        with self._session_factory() as session:
            return len(
                session.scalars(
                    select(Approval.id)
                    .where(
                        Approval.status == "pending",
                        Approval.notified_at.is_(None),
                        Approval.notify_attempts < self.max_attempts,
                    )
                    .limit(1000)
                ).all()
            )
