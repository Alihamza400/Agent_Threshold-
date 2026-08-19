"""Confirmation + reorg monitor tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from at_shared.models import Transaction
from blockchain.config import ChainConfig
from execution_service.monitor import ConfirmMonitor
from helpers_exec import CHAIN, FakeRPC, receipt


def _chain(_chain_id: str) -> ChainConfig:
    return ChainConfig(CHAIN, ["https://rpc.mon.test"], confirmations=2)


def _monitor(session_factory, *, rpc=None) -> ConfirmMonitor:
    fake = rpc or FakeRPC(block_number=12)
    return ConfirmMonitor(
        session_factory=session_factory,
        chain_resolver=_chain,
        rpc_factory=lambda _c: fake,
    )


@pytest.mark.asyncio
async def test_confirm_marks_executed_at_depth(
    session_factory, org_id, make_account, seed_transaction
) -> None:
    account = make_account()
    tx_id = seed_transaction(
        org_id=org_id,
        wallet=account.address,
        status="broadcast",
    )
    with session_factory() as s:
        tx = s.get(Transaction, tx_id)
        tx.tx_hash = "0x" + "b" * 64
        tx.nonce = 0
        tx.broadcast_at = datetime.now(UTC)
        s.commit()

    # tip=12, receipt block=10 -> depth 2 == confirmations(2) -> executed
    rpc = FakeRPC(block_number=12, receipt=receipt(10))
    executed = await _monitor(session_factory, rpc=rpc).confirm_broadcasts()
    assert executed == 1
    with session_factory() as s:
        tx = s.get(Transaction, tx_id)
        assert tx.status == "executed"
        assert tx.block_number == 10
        assert tx.confirmed_at is not None


@pytest.mark.asyncio
async def test_confirm_waits_until_depth_reached(
    session_factory, org_id, make_account, seed_transaction
) -> None:
    account = make_account()
    tx_id = seed_transaction(org_id=org_id, wallet=account.address, status="broadcast")
    with session_factory() as s:
        tx = s.get(Transaction, tx_id)
        tx.tx_hash = "0x" + "b" * 64
        tx.broadcast_at = datetime.now(UTC)
        s.commit()

    rpc = FakeRPC(block_number=11, receipt=receipt(10))  # depth 1 < 2
    assert await _monitor(session_factory, rpc=rpc).confirm_broadcasts() == 0
    with session_factory() as s:
        assert s.get(Transaction, tx_id).status == "broadcast"


@pytest.mark.asyncio
async def test_reorg_flags_orphaned_block(
    session_factory, org_id, make_account, seed_transaction
) -> None:
    account = make_account()
    tx_id = seed_transaction(org_id=org_id, wallet=account.address, status="executed")
    with session_factory() as s:
        tx = s.get(Transaction, tx_id)
        tx.tx_hash = "0x" + "b" * 64
        tx.block_number = 10
        tx.confirmed_at = datetime.now(UTC)
        tx.executed_at = tx.confirmed_at
        s.commit()

    # reorg: receipt now reports a different block for the same hash
    rpc = FakeRPC(block_number=13, receipt=receipt(9))
    flagged = await _monitor(session_factory, rpc=rpc).detect_reorgs()
    assert flagged == [tx_id]
    with session_factory() as s:
        assert s.get(Transaction, tx_id).status == "reorged"


@pytest.mark.asyncio
async def test_reorg_detects_missing_receipt(
    session_factory, org_id, make_account, seed_transaction
) -> None:
    account = make_account()
    tx_id = seed_transaction(org_id=org_id, wallet=account.address, status="executed")
    with session_factory() as s:
        tx = s.get(Transaction, tx_id)
        tx.tx_hash = "0x" + "b" * 64
        tx.block_number = 10
        tx.confirmed_at = datetime.now(UTC)
        tx.executed_at = tx.confirmed_at
        s.commit()

    rpc = FakeRPC(block_number=13, receipt=None)
    assert await _monitor(session_factory, rpc=rpc).detect_reorgs() == [tx_id]
