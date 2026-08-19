"""Channel tests: delivery success, delivery failure, invalid URL, payload shape."""

from __future__ import annotations

import httpx
import pytest
import respx
from notification_service.channels import (
    DeliveryError,
    NotificationPayload,
    WebhookChannel,
)

SAMPLE = NotificationPayload(
    approval_id="appr-1",
    org_id="org-1",
    agent_id="agt-1",
    agent_name="trader-bot",
    transaction_id="tx-1",
    chain_id="ethereum",
    from_address="0x1111111111111111111111111111111111111111",
    to_address="0x2222222222222222222222222222222222222222",
    value_wei=12345,
    risk_summary="high",
    reasons=["new counterparty"],
    confidence=0.87,
    expires_at="2026-08-18T12:00:00Z",
)


def test_channel_rejects_non_absolute_url() -> None:
    with pytest.raises(ValueError):
        WebhookChannel("hooks.slack.com/services/xxx", slack_format=True)


@respx.mock
async def test_webhook_channel_sends_json_payload() -> None:
    route = respx.post("https://hook.example/escalation").mock(return_value=httpx.Response(200))
    channel = WebhookChannel("https://hook.example/escalation", slack_format=False)
    await channel.send(SAMPLE)
    assert route.called
    body = route.calls.last.request.content
    assert b'"type":"escalation"' in body
    assert b'"approval_id":"appr-1"' in body


@respx.mock
async def test_slack_channel_wraps_in_text_envelope() -> None:
    route = respx.post("https://hooks.slack.com/services/ABC").mock(
        return_value=httpx.Response(200)
    )
    channel = WebhookChannel("https://hooks.slack.com/services/ABC", slack_format=True)
    await channel.send(SAMPLE)
    body = __import__("json").loads(route.calls.last.request.content)
    assert set(body.keys()) == {"text"}
    assert "trader-bot" in body["text"]
    assert "AgentThreshold escalation requires approval" in body["text"]


@respx.mock
async def test_channel_raises_delivery_error_on_http_error() -> None:
    respx.post("https://hook.example/escalation").mock(side_effect=httpx.ConnectError("boom"))
    channel = WebhookChannel("https://hook.example/escalation", slack_format=False)
    with pytest.raises(DeliveryError):
        await channel.send(SAMPLE)


@respx.mock
async def test_channel_raises_delivery_error_on_status_500() -> None:
    respx.post("https://hook.example/escalation").mock(return_value=httpx.Response(500))
    channel = WebhookChannel("https://hook.example/escalation", slack_format=False)
    with pytest.raises(DeliveryError):
        await channel.send(SAMPLE)
