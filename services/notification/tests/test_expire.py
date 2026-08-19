"""Fail-closed expiry tests: overdue escalations reject by default."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from at_shared.models import Approval, Transaction
from notification_service.expire import expire_overdue


def _load(session_factory, approval_id: str, tx_id: str) -> tuple[Approval, Transaction]:
    with session_factory() as s:
        s.expire_all()
        return s.get(Approval, approval_id), s.get(Transaction, tx_id)


def test_overdue_pending_expires_and_rejects_tx(session_factory, org_id) -> None:
    from tests.helpers import seed_escalation

    approval_id, _ = seed_escalation(
        session_factory,
        org_id=org_id,
        expires_at=datetime.now(UTC) - timedelta(minutes=5),
    )
    with session_factory() as s:
        tx_id = s.get(Approval, approval_id).transaction_id

    expired = expire_overdue(session_factory, ttl_minutes=60)
    assert expired == 1
    approval, tx = _load(session_factory, approval_id, tx_id)
    assert approval.status == "expired"
    assert tx.status == "rejected"  # fail-closed default reject


def test_future_escalation_not_expired(session_factory, org_id) -> None:
    from tests.helpers import seed_escalation

    approval_id, _ = seed_escalation(
        session_factory,
        org_id=org_id,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    assert expire_overdue(session_factory, ttl_minutes=60) == 0
    with session_factory() as s:
        s.expire_all()
        assert s.get(Approval, approval_id).status == "pending"


def test_approved_escalation_not_expired(session_factory, org_id) -> None:
    from tests.helpers import seed_escalation

    approval_id, _ = seed_escalation(
        session_factory,
        org_id=org_id,
        status="approved",
        expires_at=datetime.now(UTC) - timedelta(minutes=5),
    )
    assert expire_overdue(session_factory, ttl_minutes=60) == 0
    with session_factory() as s:
        s.expire_all()
        assert s.get(Approval, approval_id).status == "approved"


def test_expired_without_expires_at_is_untouched(session_factory, org_id) -> None:
    from tests.helpers import seed_escalation

    approval_id, _ = seed_escalation(session_factory, org_id=org_id, expires_at=None)
    assert expire_overdue(session_factory, ttl_minutes=60) == 0
    with session_factory() as s:
        s.expire_all()
        assert s.get(Approval, approval_id).status == "pending"
