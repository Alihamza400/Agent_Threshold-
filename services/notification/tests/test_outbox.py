"""Outbox tests: claim, deliver, retry scheduling, backoff, attempt cap."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from at_shared.models import Approval
from notification_service.outbox import NotificationOutbox


def _load(session_factory, approval_id: str) -> Approval:
    with session_factory() as s:
        s.expire_all()
        return s.get(Approval, approval_id)


def test_claim_returns_fresh_pending(session_factory, escalation_id) -> None:
    outbox = NotificationOutbox(session_factory)
    rows = outbox.claim_due()
    assert [r.id for r in rows] == [escalation_id]
    # claim marks in-flight so a second claim does not double-deliver
    assert outbox.claim_due() == []
    assert _load(session_factory, escalation_id).notify_attempts == 1


def test_delivered_marks_notified(session_factory, escalation_id) -> None:
    outbox = NotificationOutbox(session_factory)
    outbox.claim_due()
    outbox.mark_delivered(escalation_id)
    row = _load(session_factory, escalation_id)
    assert row.notified_at is not None
    assert row.notify_last_error is None
    assert outbox.claim_due() == []


def test_failed_schedule_retry_with_exponential_backoff(session_factory, escalation_id) -> None:
    outbox = NotificationOutbox(session_factory, backoff_base_seconds=2.0)
    outbox.claim_due()  # attempts now 1
    outbox.schedule_retry(escalation_id, "webhook 500")
    row = _load(session_factory, escalation_id)
    assert row.notify_last_error == "webhook 500"
    assert row.notify_attempts == 1
    expected = datetime.now(UTC) + timedelta(seconds=2.0)
    assert abs((row.notify_next_attempt_at - expected).total_seconds()) < 5.0

    # next backoff doubles to 4s
    outbox.claim_due()
    outbox.schedule_retry(escalation_id, "webhook 500 again")
    row = _load(session_factory, escalation_id)
    expected = datetime.now(UTC) + timedelta(seconds=4.0)
    assert abs((row.notify_next_attempt_at - expected).total_seconds()) < 5.0


def test_attempt_cap_excludes_approval_from_claim(session_factory, escalation_id) -> None:
    outbox = NotificationOutbox(session_factory, max_attempts=2)
    outbox.claim_due()
    outbox.schedule_retry(escalation_id, "fail")
    # advance the schedule so the retry is due
    with session_factory() as s:
        row = s.get(Approval, escalation_id)
        row.notify_next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
        s.commit()
    outbox.claim_due()
    outbox.schedule_retry(escalation_id, "fail again")
    row = _load(session_factory, escalation_id)
    assert row.notify_attempts == 2
    assert row.notify_next_attempt_at is None  # exhausted -> stop retrying
    assert outbox.claim_due() == []


def test_approved_escalation_is_never_claimed(session_factory, org_id) -> None:
    from tests.helpers import seed_escalation

    approval_id, _ = seed_escalation(session_factory, org_id=org_id, status="approved")
    outbox = NotificationOutbox(session_factory)
    assert outbox.claim_due() == []


def test_pending_due_count_reflects_queue(session_factory, escalation_id) -> None:
    outbox = NotificationOutbox(session_factory)
    before = outbox.pending_due_count()
    assert before >= 1
    outbox.claim_due()
    outbox.mark_delivered(escalation_id)
    assert outbox.pending_due_count() == before - 1
