"""Escalation notification + on-call paging worker loops (8.4, 9.6).

Per tick, in dependency order:
  1. Expire overdue escalations (fail-closed default reject) — before any
     delivery, so we never notify about something already default-rejected.
  2. Deliver due escalation notifications with retry/backoff.
  3. Page on-call for open incidents and send "resolve" events for resolved
     incidents (PagerDuty Events v2), each with retry/backoff + lease.

Delivery is best-effort notification; the DB rows remain the source of truth
for both the human decision queue and incident history regardless of delivery
success.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from at_shared.config import get_settings
from at_shared.db import get_session_factory
from at_shared.models import Agent, Approval, Transaction
from sqlalchemy import select
from sqlalchemy.orm import Session

from notification_service.channels import Channel, DeliveryError, NotificationPayload
from notification_service.expire import expire_overdue
from notification_service.incidents import (
    IncidentNotifierError,
    IncidentOutbox,
    build_notifier,
)
from notification_service.outbox import NotificationOutbox

logger = logging.getLogger("notification_service.worker")


@dataclass
class NotificationRunner:
    """Composes the worker pieces so tests can drive ticks directly."""

    outbox: NotificationOutbox
    channels: dict[str, Channel]  # org_id -> delivery channel
    expiry_ttl_minutes: int
    incident_outbox: IncidentOutbox = field(default_factory=lambda: IncidentOutbox(get_session_factory()))
    incident_notifier: object = field(default_factory=lambda: build_notifier())
    session_factory: Callable[[], Session] = field(default=get_session_factory)
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep

    def _resolve_payload(self, db: Session, approval: Approval) -> NotificationPayload:
        tx = db.get(Transaction, approval.transaction_id)
        agent = db.get(Agent, approval.agent_id)
        return NotificationPayload(
            approval_id=approval.id,
            org_id=approval.org_id,
            agent_id=approval.agent_id,
            agent_name=agent.name if agent else None,
            transaction_id=approval.transaction_id,
            chain_id=tx.chain_id if tx else "",
            from_address=tx.from_address if tx else "",
            to_address=tx.to_address if tx else None,
            value_wei=tx.value_wei if tx else 0,
            risk_summary=approval.risk_summary,
            reasons=approval.reasons or [],
            confidence=approval.confidence,
            expires_at=approval.expires_at.isoformat() if approval.expires_at else None,
        )

    def _resolve_payloads_bulk(
        self, db: Session, approvals: list[Approval]
    ) -> list[tuple[Approval, NotificationPayload]]:
        """Batch-load related records and build payloads for all approvals."""
        tx_ids = {a.transaction_id for a in approvals}
        agent_ids = {a.agent_id for a in approvals}
        txns = {
            tx.id: tx
            for tx in db.scalars(select(Transaction).where(Transaction.id.in_(tx_ids))).all()
        } if tx_ids else {}
        agents = {
            ag.id: ag
            for ag in db.scalars(select(Agent).where(Agent.id.in_(agent_ids))).all()
        } if agent_ids else {}
        results = []
        for approval in approvals:
            tx = txns.get(approval.transaction_id)
            agent = agents.get(approval.agent_id)
            payload = NotificationPayload(
                approval_id=approval.id,
                org_id=approval.org_id,
                agent_id=approval.agent_id,
                agent_name=agent.name if agent else None,
                transaction_id=approval.transaction_id,
                chain_id=tx.chain_id if tx else "",
                from_address=tx.from_address if tx else "",
                to_address=tx.to_address if tx else None,
                value_wei=tx.value_wei if tx else 0,
                risk_summary=approval.risk_summary,
                reasons=approval.reasons or [],
                confidence=approval.confidence,
                expires_at=approval.expires_at.isoformat() if approval.expires_at else None,
            )
            results.append((approval, payload))
        return results

    async def tick(self) -> dict[str, int]:
        expire_overdue(self.session_factory, ttl_minutes=self.expiry_ttl_minutes)
        delivered = 0
        retried = 0
        due = self.outbox.claim_due()
        if due:
            with self.session_factory() as db:
                bulk_payloads = self._resolve_payloads_bulk(db, list(due))
            for approval, payload in bulk_payloads:
                channel = self.channels.get(approval.org_id)
                if channel is None:
                    self.outbox.mark_delivered(approval.id)
                    delivered += 1
                    continue
                try:
                    await channel.send(payload)
                except DeliveryError as exc:
                    logger.warning("delivery failed for %s: %s", approval.id, exc)
                    self.outbox.schedule_retry(approval.id, str(exc))
                    retried += 1
                    continue
                self.outbox.mark_delivered(approval.id)
                delivered += 1

        incidents_paged = 0
        incidents_retried = 0
        for incident in self.incident_outbox.claim_due():
            try:
                await self.incident_notifier.send(incident)
            except IncidentNotifierError as exc:
                logger.warning("incident paging failed for %s: %s", incident.id, exc)
                self.incident_outbox.schedule_retry(incident.id, str(exc))
                incidents_retried += 1
                continue
            self.incident_outbox.mark_paged(incident.id)
            incidents_paged += 1

        return {
            "delivered": delivered,
            "retried": retried,
            "incidents_paged": incidents_paged,
            "incidents_retried": incidents_retried,
        }

    async def run(self, poll_seconds: float = 0.5) -> None:
        while True:
            try:
                await self.tick()
            except Exception:  # noqa: BLE001 - the loop must survive transient faults
                logger.exception("notification tick failed")
            await self.sleep(poll_seconds)


def build_runner(
    *,
    channels: dict[str, Channel] | None = None,
    session_factory: Callable[[], Session] | None = None,
    max_attempts: int | None = None,
    backoff_base_seconds: float | None = None,
    ttl_minutes: int | None = None,
) -> NotificationRunner:
    """Wire the runner from settings (used by the service entrypoint)."""
    settings = get_settings()
    factory = session_factory or get_session_factory()
    return NotificationRunner(
        outbox=NotificationOutbox(
            factory,
            max_attempts=max_attempts or settings.notify_max_attempts,
            backoff_base_seconds=backoff_base_seconds or settings.notify_backoff_base_seconds,
        ),
        channels=channels
        or build_channels(settings.notification_webhooks, settings.notification_slack_format),
        expiry_ttl_minutes=ttl_minutes or settings.escalation_ttl_minutes,
        incident_outbox=IncidentOutbox(
            factory,
            max_attempts=settings.incident_max_attempts,
            backoff_base_seconds=settings.incident_backoff_base_seconds,
        ),
        incident_notifier=build_notifier(
            routing_key=settings.pagerduty_routing_key,
            webhook_url=settings.incident_webhook_url,
        ),
        session_factory=factory,
    )


def build_channels(webhooks: str, slack_format: bool) -> dict[str, Channel]:
    """Parse `org_id=url,org_id=url` settings into {org_id: Channel}."""
    from notification_service.channels import WebhookChannel

    channels: dict[str, Channel] = {}
    for pair in (webhooks or "").split(","):
        pair = pair.strip()
        if not pair:
            continue
        if "=" not in pair:
            logger.warning("ignoring malformed webhook entry %r (expected org_id=url)", pair)
            continue
        org_id, url = pair.split("=", 1)
        channels[org_id.strip()] = WebhookChannel(url.strip(), slack_format=slack_format)
    return channels
