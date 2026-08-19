"""Execution adapter tests: prepare/submit/cancel + fail-closed guards."""

from __future__ import annotations

import asyncio

import pytest
from at_shared.models import Transaction
from blockchain.config import ChainConfig
from blockchain.errors import RPCError
from blockchain.nonce import NonceAllocator
from execution_service.errors import (
    BroadcastError,
    DecisionNotApprovedError,
    SignedTxInvalidError,
    TokenConsumedError,
)
from execution_service.executor import ExecutionAdapter
from execution_service.tokens import DecisionTokenStore
from helpers_exec import CHAIN, FakeRPC

PRIMARY = "https://rpc.exec.test"
FALLBACK = "https://rpc.exec-fallback.test"


def _chain(_chain_id: str) -> ChainConfig:
    return ChainConfig(CHAIN, [PRIMARY, FALLBACK], confirmations=2)


def _adapter(session_factory, *, rpc=None, sleep=asyncio.sleep, **kw) -> ExecutionAdapter:
    fake_rpc = rpc or FakeRPC()

    def factory(_chain):
        return fake_rpc

    return ExecutionAdapter(
        session_factory=session_factory,
        tokens=DecisionTokenStore(ttl_seconds=300),
        nonce_allocator=NonceAllocator(sync_nonce_getter=lambda _w: 0),
        chain_resolver=_chain,
        rpc_factory=factory,
        sleep=sleep,
        **kw,
    )


def test_prepare_issues_token_and_reserves_nonce(
    session_factory, org_id, seed_transaction, make_account
) -> None:
    account = make_account()
    tx_id = seed_transaction(org_id=org_id, wallet=account.address)
    result = _adapter(session_factory).prepare(tx_id)
    assert result.nonce == 0
    assert result.chain_id == CHAIN.value
    assert result.decision_token

    # re-prepare reuses the SAME nonce (no gap) and mints a fresh token
    again = _adapter(session_factory).prepare(tx_id)
    assert again.nonce == 0
    assert again.decision_token != result.decision_token


def test_prepare_rejects_non_approved(
    session_factory, org_id, seed_transaction, make_account
) -> None:
    account = make_account()
    tx_id = seed_transaction(org_id=org_id, wallet=account.address, status="rejected")
    with pytest.raises(DecisionNotApprovedError):
        _adapter(session_factory).prepare(tx_id)


@pytest.mark.asyncio
async def test_submit_happy_path(
    session_factory, org_id, seed_transaction, make_account, sign_tx
) -> None:
    account = make_account()
    tx_id = seed_transaction(org_id=org_id, wallet=account.address)
    adapter = _adapter(session_factory)
    prepared = adapter.prepare(tx_id)
    raw = sign_tx(account, nonce=prepared.nonce, to="0x" + "2" * 40)
    result = await adapter.submit(tx_id, prepared.decision_token, raw)
    assert result.tx_hash == FakeRPC().tx_hash
    with session_factory() as s:
        tx = s.get(Transaction, tx_id)
        assert tx.status == "broadcast"
        assert tx.tx_hash == result.tx_hash
        assert tx.broadcast_at is not None
        assert tx.broadcast_attempts == 1


@pytest.mark.asyncio
async def test_submit_single_use_token_rejects_replay(
    session_factory, org_id, seed_transaction, make_account, sign_tx
) -> None:
    account = make_account()
    tx_id = seed_transaction(org_id=org_id, wallet=account.address)
    adapter = _adapter(session_factory)
    prepared = adapter.prepare(tx_id)
    raw = sign_tx(account, nonce=prepared.nonce, to="0x" + "2" * 40)
    await adapter.submit(tx_id, prepared.decision_token, raw)
    # second submit with the same token must be rejected (single-use)
    with pytest.raises(TokenConsumedError):
        await adapter.submit(tx_id, prepared.decision_token, raw)


@pytest.mark.asyncio
async def test_submit_wrong_token_rejected(
    session_factory, org_id, seed_transaction, make_account, sign_tx
) -> None:
    account = make_account()
    tx_id = seed_transaction(org_id=org_id, wallet=account.address)
    adapter = _adapter(session_factory)
    adapter.prepare(tx_id)
    raw = sign_tx(account, nonce=0, to="0x" + "2" * 40)
    with pytest.raises(TokenConsumedError):
        await adapter.submit(tx_id, "not-the-token", raw)


@pytest.mark.asyncio
async def test_submit_tampered_payload_rejected_and_tx_stays_approved(
    session_factory, org_id, seed_transaction, make_account, sign_tx
) -> None:
    account = make_account()
    tx_id = seed_transaction(org_id=org_id, wallet=account.address, value_wei=1000)
    adapter = _adapter(session_factory)
    prepared = adapter.prepare(tx_id)
    raw = sign_tx(account, nonce=prepared.nonce, to="0x" + "2" * 40, value=999)  # tampered value
    with pytest.raises(SignedTxInvalidError):
        await adapter.submit(tx_id, prepared.decision_token, raw)
    with session_factory() as s:
        assert s.get(Transaction, tx_id).status == "approved"


@pytest.mark.asyncio
async def test_submit_broadcast_failure_reverts_and_retries(
    session_factory, org_id, seed_transaction, make_account, sign_tx
) -> None:
    account = make_account()
    tx_id = seed_transaction(org_id=org_id, wallet=account.address)

    class FlakyRPC(FakeRPC):
        def __init__(self):
            super().__init__()
            self.attempts = 0

        async def send_raw_transaction(self, raw):
            self.attempts += 1
            raise RPCError("mempool rejected")

    flaky = FlakyRPC()
    adapter = _adapter(
        session_factory, rpc=flaky, max_broadcast_attempts=3, backoff_base_seconds=0.01
    )
    prepared = adapter.prepare(tx_id)
    raw = sign_tx(account, nonce=prepared.nonce, to="0x" + "2" * 40)
    with pytest.raises(BroadcastError):
        await adapter.submit(tx_id, prepared.decision_token, raw)
    assert flaky.attempts == 3  # exponential-backoff retries exhausted
    with session_factory() as s:
        tx = s.get(Transaction, tx_id)
        assert tx.status == "approved"  # reverted; a fresh token is required
        assert tx.broadcast_attempts == 1  # attempt counter survived


def test_cancel_rejects_approved_tx(
    session_factory, org_id, seed_transaction, make_account
) -> None:
    account = make_account()
    tx_id = seed_transaction(org_id=org_id, wallet=account.address)
    adapter = _adapter(session_factory)
    token = adapter.prepare(tx_id).decision_token
    adapter.cancel(tx_id)
    with session_factory() as s:
        assert s.get(Transaction, tx_id).status == "cancelled"
    # token revoked -> cannot be consumed afterwards
    assert adapter._tokens.consume(tx_id, token) is False  # noqa: SLF001


def test_cancel_rejects_non_pending(
    session_factory, org_id, seed_transaction, make_account
) -> None:
    account = make_account()
    tx_id = seed_transaction(org_id=org_id, wallet=account.address, status="executed")
    with pytest.raises(DecisionNotApprovedError):
        _adapter(session_factory).cancel(tx_id)
