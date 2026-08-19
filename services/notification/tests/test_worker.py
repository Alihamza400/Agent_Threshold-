"""Worker integration tests: tick delivers, retries, and expires fail-closed."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import respx
from at_shared.models import Approval, Transaction
from notification_service.channels import NotificationPayload, WebhookChannel
from notification_service.outbox import NotificationOutbox
from notification_service.worker import NotificationRunner, build_channels


def _make_runner(session_factory, *, org_id: str, channels=None, **kw) -> NotificationRunner:
    return NotificationRunner(
        outbox=NotificationOutbox(session_factory, **kw),
        channels=channels or {},
        expiry_ttl_minutes=60,
        session_factory=session_factory,
        sleep=asyncio.sleep,
    )


@respx.mock
async def test_tick_delivers_to_channel_and_marks_notified(
    session_factory, org_id, escalation_id
) -> None:
    route = respx.post("https://hooks.slack.com/services/ORG").mock(
        return_value=httpx.Response(200)
    )
    channel = WebhookChannel("https://hooks.slack.com/services/ORG", slack_format=True)
    runner = _make_runner(session_factory, org_id=org_id, channels={org_id: channel})

    result = await runner.tick()
    assert result == {"delivered": 1, "retried": 0}
    assert route.called
    with session_factory() as s:
        s.expire_all()
        assert s.get(Approval, escalation_id).notified_at is not None


async def test_tick_without_channel_marks_notified_not_delivered(
    session_factory, escalation_id
) -> None:
    runner = _make_runner(session_factory, org_id="unused")
    result = await runner.tick()
    assert result == {"delivered": 1, "retried": 0}
    with session_factory() as s:
        s.expire_all()
        row = s.get(Approval, escalation_id)
        assert row.notified_at is not None
        assert row.notify_attempts == 1


@respx.mock
async def test_tick_retries_on_failed_delivery(session_factory, org_id, escalation_id) -> None:
    respx.post("https://hook.example/retry").mock(return_value=httpx.Response(503))
    channel = WebhookChannel("https://hook.example/retry", slack_format=False)
    runner = _make_runner(session_factory, org_id=org_id, channels={org_id: channel})

    result = await runner.tick()
    assert result == {"delivered": 0, "retried": 1}
    with session_factory() as s:
        s.expire_all()
        row = s.get(Approval, escalation_id)
        assert row.notified_at is None
        assert row.notify_attempts == 1
        assert row.notify_last_error is not None


async def test_tick_expires_overdue_before_delivery(session_factory, org_id) -> None:
    from tests.helpers import seed_escalation

    overdue_id, _ = seed_escalation(
        session_factory,
        org_id=org_id,
        expires_at=datetime.now(UTC) - timedelta(minutes=5),
    )
    sent: list[NotificationPayload] = []

    class RecordingChannel:
        async def send(self, payload: NotificationPayload) -> None:
            sent.append(payload)

    runner = _make_runner(session_factory, org_id=org_id, channels={org_id: RecordingChannel()})
    await runner.tick()
    assert sent == []  # nothing delivered for an already-rejected escalation
    with session_factory() as s:
        s.expire_all()
        row = s.get(Approval, overdue_id)
        assert row.status == "expired"
        tx = s.get(Transaction, row.transaction_id)
        assert tx.status == "rejected"


def test_build_channels_parses_org_url_pairs() -> None:
    channels = build_channels(
        "org1=https://hooks.slack.com/AAA, org2=https://hook.example/bbb",
        slack_format=True,
    )
    assert set(channels.keys()) == {"org1", "org2"}
    assert isinstance(channels["org1"], WebhookChannel)


def test_build_channels_ignores_malformed_and_empty() -> None:
    assert build_channels("", slack_format=True) == {}
    assert build_channels("no-equals-here", slack_format=True) == {}
