"""Test seeding helpers for the notification service suite."""

from __future__ import annotations

from at_shared.models import Agent, Approval, Transaction
from at_shared.uuid7 import uuid7


def seed_escalation(
    session_factory,
    *,
    org_id: str,
    status: str = "pending",
    expires_at=None,
) -> tuple[str, str]:
    """Insert an agent + pending transaction + approval; return (approval_id, agent_id)."""
    with session_factory() as s:
        agent = Agent(
            id=uuid7(),
            org_id=org_id,
            name="notify-agent",
            wallet_address="0x" + "1" * 40,
        )
        tx = Transaction(
            id=uuid7(),
            org_id=org_id,
            agent_id=agent.id,
            chain_id="ethereum",
            from_address="0x" + "1" * 40,
            to_address="0x" + "2" * 40,
            value_wei=12345,
            raw_params={},
            decision="escalate",
            status="pending",
        )
        approval = Approval(
            id=uuid7(),
            org_id=org_id,
            agent_id=agent.id,
            transaction_id=tx.id,
            decision="escalate",
            status=status,
            reasons=["new counterparty", "amount > threshold"],
            risk_summary="high",
            confidence=0.87,
            expires_at=expires_at,
        )
        s.add_all([agent, tx, approval])
        s.commit()
        return approval.id, agent.id
