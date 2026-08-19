"""Delivery channels for escalation notifications (task 8.4).

A channel delivers a notification payload to a webhook endpoint. Delivery is
best-effort NOTIFICATION — a failure must never affect the approval outcome
(the human decision queue is the source of truth). Failures raise
`DeliveryError` so the worker can schedule a retry with backoff.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

logger = logging.getLogger("notification_service.channels")

_DELIVERY_TIMEOUT = 5.0


class DeliveryError(Exception):
    """The webhook delivery failed; the worker will retry with backoff."""


@dataclass(frozen=True)
class NotificationPayload:
    """Plain-JSON notification payload for one escalation."""

    approval_id: str
    org_id: str
    agent_id: str
    agent_name: str | None
    transaction_id: str
    chain_id: str
    from_address: str
    to_address: str | None
    value_wei: int
    risk_summary: str | None
    reasons: list[str]
    confidence: float
    expires_at: str | None
    dashboard_url: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "type": "escalation",
            "approval_id": self.approval_id,
            "org_id": self.org_id,
            "agent": {"id": self.agent_id, "name": self.agent_name},
            "transaction": {
                "id": self.transaction_id,
                "chain_id": self.chain_id,
                "from": self.from_address,
                "to": self.to_address,
                "value_wei": self.value_wei,
            },
            "risk_summary": self.risk_summary,
            "reasons": self.reasons,
            "confidence": self.confidence,
            "expires_at": self.expires_at,
            "dashboard_url": self.dashboard_url,
            "action": "A human approver must act before this transaction may be executed.",
        }


class Channel(Protocol):
    async def send(self, payload: NotificationPayload) -> None: ...


class WebhookChannel:
    """Generic webhook delivery over HTTPS (idempotent POST, bounded timeout)."""

    def __init__(self, url: str, *, slack_format: bool, timeout: float = _DELIVERY_TIMEOUT) -> None:
        if not url.lower().startswith(("https://", "http://")):
            raise ValueError(f"webhook URL must be absolute: {url!r}")
        self.url = url
        self.slack_format = slack_format
        self.timeout = timeout

    async def send(self, payload: NotificationPayload) -> None:
        body: Any = {"text": self._slack_text(payload)} if self.slack_format else payload.to_json()
        async with httpx.AsyncClient(timeout=httpx.Timeout(self.timeout)) as client:
            try:
                response = await client.post(self.url, json=body)
            except httpx.HTTPError as exc:
                raise DeliveryError(f"webhook delivery failed: {exc}") from exc
        if response.status_code >= 400:
            raise DeliveryError(
                f"webhook rejected payload with status {response.status_code}: {response.text[:200]}"
            )

    @staticmethod
    def _slack_text(payload: NotificationPayload) -> str:
        lines = [
            ":warning: *AgentThreshold escalation requires approval*",
            f"*Agent:* {payload.agent_name or payload.agent_id}",
            f"*Chain:* {payload.chain_id}",
            f"*Value:* {payload.value_wei} wei",
            f"*From:* `{payload.from_address}`",
            f"*To:* `{payload.to_address or 'contract deployment'}`",
            f"*Risk:* {payload.risk_summary or 'no risk summary'}",
        ]
        if payload.reasons:
            lines.append(f"*Reasons:* {'; '.join(payload.reasons)}")
        if payload.expires_at:
            lines.append(f"*Expires:* {payload.expires_at} (unresolved escalations reject)")
        if payload.dashboard_url:
            lines.append(f"*Review:* {payload.dashboard_url}")
        return "\n".join(lines)
