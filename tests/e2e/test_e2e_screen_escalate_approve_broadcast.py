"""Phase 8.7 E2E: SDK-wrapped agent screened end-to-end on testnet.

Scenario (TRD Section 12 / IMPLEMENTATION_PLAN 8.7):

    Agent SDK wraps the signer and screens a payment to a NEW/unlisted
    address -> the pipeline ESCALATES (first transaction to a previously
    unseen counterparty, fail-closed) -> NO signature is produced and
    nothing is broadcast -> the escalation is delivered through the
    notification outbox -> an approver approves via the gateway -> only then
    does the Execution Adapter (single-use token + locked nonce + signed-tx
    validation) broadcast.

Assertions enforce the security invariants end to end:
    * non-custodial: the signer is NEVER invoked on ESCALATE
    * zero premature execution: no broadcast before the human approval
    * audit-everything: the decision leaf + audit record are persisted
"""

from __future__ import annotations

import asyncio

import pytest
from agentthreshold import AgentThresholdClient, ChainId, ScreeningEscalatedError
from at_shared.models import Approval, AuditRecord, Transaction
from blockchain.config import ChainConfig
from blockchain.nonce import NonceAllocator
from execution_service.errors import DecisionNotApprovedError
from execution_service.executor import ExecutionAdapter
from execution_service.tokens import DecisionTokenStore
from execution_service.validation import CHAIN_IDS
from notification_service.outbox import NotificationOutbox
from notification_service.worker import NotificationRunner
from sqlalchemy import select

NEW_CP = "0x9999999999999999999999999999999999999999"  # unlisted counterparty
VALUE_WEI = 10**17  # 0.1 ETH
GAS_LIMIT = 21000
GAS_PRICE = 1_000_000_000


class FakeRPC:
    """Records every broadcast attempt; serves no confirmations (E2E asserts
    broadcast only, confirmation monitoring is covered by its own suite)."""

    def __init__(self) -> None:
        self.broadcast_raw: list[str] = []
        self.tx_hash = "0x" + "a" * 64

    async def send_raw_transaction(self, raw: str) -> str:
        self.broadcast_raw.append(raw)
        return self.tx_hash


def _build_adapter(session_factory, rpc: FakeRPC) -> ExecutionAdapter:
    return ExecutionAdapter(
        session_factory=session_factory,
        tokens=DecisionTokenStore(ttl_seconds=300),
        nonce_allocator=NonceAllocator(sync_nonce_getter=lambda _w: 0),
        chain_resolver=lambda _c: ChainConfig(
            ChainId.BASE, ["https://rpc.e2e.test"], confirmations=2
        ),
        rpc_factory=lambda _c: rpc,
        max_broadcast_attempts=3,
        backoff_base_seconds=0.01,
        sleep=asyncio.sleep,
    )


def _register_agent(client, admin_token, wallet: str, name: str) -> str:
    resp = client.post(
        "/v1/agents/register",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"name": name, "wallet_address": wallet},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["agent"]["id"]


def _create_api_key(client, admin_token, agent_id: str) -> str:
    resp = client.post(
        "/v1/api-keys",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"name": "e2e-key", "agent_ids": [agent_id]},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["api_key"]


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_e2e_escalate_then_approve_then_broadcast(gateway, session_factory, account):
    client = gateway.client
    rpc = FakeRPC()
    adapter = _build_adapter(session_factory, rpc)

    # 1. Register the agent (wallet = the SDK signer's account) + scoped key
    agent_id = _register_agent(client, gateway.admin_token, account.address, "agent-e2e")
    api_key = _create_api_key(client, gateway.admin_token, agent_id)

    # 2. SDK-wrapped agent screens the payment to an UNLISTED address
    sdk = AgentThresholdClient(gateway.base_url, api_key)
    signer = lambda unsigned_tx: "SIGNED-BUT-SHOULD-NEVER-BE-CALLED"  # noqa: E731

    try:
        sdk.screen_and_sign(
            signer,
            agent_id=agent_id,
            chain_id=ChainId.BASE,
            from_address=account.address,
            to_address=NEW_CP,
            value_wei=VALUE_WEI,
            gas_limit=GAS_LIMIT,
            task_context="pay vendor invoice #1234",
        )
        raise AssertionError("expected ScreeningEscalatedError for unlisted counterparty")
    except ScreeningEscalatedError as exc:
        assert exc.decision.decision == "escalate"
        tx_id = exc.decision.transaction_id
    finally:
        sdk.close()

    # 3. State: tx persisted as escalated + a pending Approval was created
    with session_factory() as s:
        tx = s.get(Transaction, tx_id)
        assert tx is not None
        assert tx.status == "escalated"
        assert tx.to_address == NEW_CP
        assert tx.value_wei == VALUE_WEI
        approval = s.scalar(select(Approval).where(Approval.transaction_id == tx_id))
        assert approval is not None
        assert approval.status == "pending"
        assert approval.decision == "escalate"

    # 4. Notification outbox delivers the escalation (Slack/webhook path)
    runner = NotificationRunner(
        outbox=NotificationOutbox(session_factory, max_attempts=8, backoff_base_seconds=1.0),
        channels={},
        expiry_ttl_minutes=60,
        session_factory=session_factory,
    )
    result = await runner.tick()
    assert result["delivered"] == 1
    with session_factory() as s:
        approval = s.get(Approval, approval.id)
        assert approval.notified_at is not None  # left the delivery queue

    # 5. FAIL-CLOSED: nothing is broadcast before the human approval
    assert rpc.broadcast_raw == []
    with pytest.raises(DecisionNotApprovedError):
        adapter.prepare(tx_id)  # tx.status is "escalated", not "approved"

    # 6. Approver approves through the gateway (JWT-protected, human-in-loop)
    resp = client.post(
        f"/v1/approvals/{approval.id}/approve",
        headers={"Authorization": f"Bearer {gateway.approver_token}"},
        json={"note": "vendor invoice confirmed by finance"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "approved"
    with session_factory() as s:
        assert s.get(Transaction, tx_id).status == "approved"

    # 7. Execution Adapter broadcasts the pre-signed tx (nonce + token + validation)
    prepared = adapter.prepare(tx_id)
    assert prepared.nonce == 0  # first tx for this wallet
    raw = account.sign_transaction(
        {
            "chainId": CHAIN_IDS[ChainId.BASE],
            "nonce": prepared.nonce,
            "to": NEW_CP,
            "value": VALUE_WEI,
            "data": "0x",
            "gas": GAS_LIMIT,
            "gasPrice": GAS_PRICE,
        }
    )
    raw_hex = "0x" + raw.raw_transaction.hex()
    submitted = await adapter.submit(tx_id, prepared.decision_token, raw_hex)
    assert submitted.tx_hash == rpc.tx_hash
    assert rpc.broadcast_raw == [raw_hex]  # exactly one broadcast, correct payload
    with session_factory() as s:
        tx = s.get(Transaction, tx_id)
        assert tx.status == "broadcast"
        assert tx.tx_hash == rpc.tx_hash
        assert tx.broadcast_at is not None
        assert tx.nonce == 0

    # 8. Audit-everything: the decision leaf + record were persisted
    with session_factory() as s:
        record = s.scalar(
            select(AuditRecord).where(
                AuditRecord.transaction_id == tx_id, AuditRecord.event_type == "decision"
            )
        )
        assert record is not None
        assert record.details["decision"] == "escalate"
        assert record.details["to_address"] == NEW_CP
        assert record.event_hash  # keccak256 leaf ready for Merkle anchoring
