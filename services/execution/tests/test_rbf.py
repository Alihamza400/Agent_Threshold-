"""Stuck-tx RBF/cancel replacement tests (re-screen required)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from at_shared.models import Transaction
from at_shared.schemas.tx import Decision, DecisionType
from blockchain.config import ChainConfig
from execution_service.errors import (
    DecisionNotApprovedError,
    GasCeilingError,
    SignedTxInvalidError,
    TokenConsumedError,
)
from execution_service.rbf import StuckTxHandler, flag_stuck
from execution_service.tokens import DecisionTokenStore
from helpers_exec import CHAIN, FakeRPC


def _chain(_chain_id: str) -> ChainConfig:
    return ChainConfig(CHAIN, ["https://rpc.rbf.test"], confirmations=2)


def _make_stuck(
    session_factory,
    org_id,
    wallet,
    seed_transaction,
    *,
    gas_price=1_000_000_000,
    nonce=0,
    value=1000,
):
    tx_id = seed_transaction(
        org_id=org_id,
        wallet=wallet,
        status="stuck",
        gas_price_wei=gas_price,
        nonce=nonce,
        value_wei=value,
    )
    with session_factory() as s:
        tx = s.get(Transaction, tx_id)
        tx.tx_hash = "0x" + "c" * 64
        tx.broadcast_at = datetime.now(UTC) - timedelta(hours=1)
        tx.stuck_at = datetime.now(UTC) - timedelta(minutes=1)
        s.commit()
    return tx_id


def _handler(session_factory, *, approve=True, rpc=None) -> StuckTxHandler:
    fake_rpc = rpc or FakeRPC()

    async def rescreen(request, org_id):
        return Decision(
            decision=DecisionType.APPROVE if approve else DecisionType.REJECT,
            reasons=["replacement"],
            confidence=90.0,
        )

    return StuckTxHandler(
        session_factory=session_factory,
        tokens=DecisionTokenStore(ttl_seconds=300),
        chain_resolver=_chain,
        rpc_factory=lambda _c: fake_rpc,
        rescreen=rescreen,
        rbf_gas_bump_pct=20.0,
        cancel_gas_bump_pct=20.0,
    )


def test_flag_stuck_marks_unconfirmed(
    session_factory, org_id, make_account, seed_transaction
) -> None:
    account = make_account()
    tx_id = seed_transaction(
        org_id=org_id,
        wallet=account.address,
        status="broadcast",
        gas_price_wei=1_000_000_000,
        nonce=0,
    )
    with session_factory() as s:
        tx = s.get(Transaction, tx_id)
        tx.tx_hash = "0x" + "c" * 64
        tx.broadcast_at = datetime.now(UTC) - timedelta(hours=1)
        s.commit()
    flagged = flag_stuck(session_factory, stuck_after_seconds=60)
    assert flagged == [tx_id]
    with session_factory() as s:
        assert s.get(Transaction, tx_id).status == "stuck"


@pytest.mark.asyncio
async def test_rbf_replaces_with_re_screen(
    session_factory, org_id, make_account, seed_transaction, sign_tx
) -> None:
    account = make_account()
    tx_id = _make_stuck(
        session_factory, org_id, account.address, seed_transaction, gas_price=1_000_000_000
    )
    handler = _handler(session_factory)
    token = handler._tokens.issue(tx_id)  # noqa: SLF001

    bumped = 1_200_000_000  # +20%
    raw = sign_tx(account, nonce=0, to="0x" + "2" * 40, value=1000, gas_price=bumped)
    result = await handler.replace(tx_id, token, raw, mode="rbf")
    assert result.mode == "rbf"
    with session_factory() as s:
        tx = s.get(Transaction, tx_id)
        assert tx.status == "broadcast"
        assert tx.tx_hash == result.tx_hash
        assert tx.broadcast_attempts == 1


@pytest.mark.asyncio
async def test_rbf_below_bump_rejected(
    session_factory, org_id, make_account, seed_transaction, sign_tx
) -> None:
    account = make_account()
    tx_id = _make_stuck(
        session_factory, org_id, account.address, seed_transaction, gas_price=1_000_000_000
    )
    handler = _handler(session_factory)
    token = handler._tokens.issue(tx_id)  # noqa: SLF001

    raw = sign_tx(account, nonce=0, to="0x" + "2" * 40, value=1000, gas_price=1_000_000_001)
    with pytest.raises(GasCeilingError):
        await handler.replace(tx_id, token, raw, mode="rbf")


@pytest.mark.asyncio
async def test_cancel_zero_value_to_self(
    session_factory, org_id, make_account, seed_transaction, sign_tx
) -> None:
    account = make_account()
    tx_id = _make_stuck(session_factory, org_id, account.address, seed_transaction)
    handler = _handler(session_factory)
    token = handler._tokens.issue(tx_id)  # noqa: SLF001

    raw = sign_tx(
        account,
        nonce=0,
        to=account.address,
        value=0,
        gas_price=1_200_000_000,
    )
    result = await handler.replace(tx_id, token, raw, mode="cancel")
    assert result.mode == "cancel"


@pytest.mark.asyncio
async def test_replacement_must_be_re_screened(
    session_factory, org_id, make_account, seed_transaction, sign_tx
) -> None:
    account = make_account()
    tx_id = _make_stuck(session_factory, org_id, account.address, seed_transaction)
    handler = _handler(session_factory, approve=False)
    token = handler._tokens.issue(tx_id)  # noqa: SLF001

    raw = sign_tx(account, nonce=0, to="0x" + "2" * 40, value=1000, gas_price=1_200_000_000)
    with pytest.raises(SignedTxInvalidError):
        await handler.replace(tx_id, token, raw, mode="rbf")
    with session_factory() as s:
        assert s.get(Transaction, tx_id).status == "stuck"  # untouched


@pytest.mark.asyncio
async def test_replacement_wrong_nonce_rejected(
    session_factory, org_id, make_account, seed_transaction, sign_tx
) -> None:
    account = make_account()
    tx_id = _make_stuck(session_factory, org_id, account.address, seed_transaction, nonce=0)
    handler = _handler(session_factory)
    token = handler._tokens.issue(tx_id)  # noqa: SLF001

    raw = sign_tx(account, nonce=5, to="0x" + "2" * 40, value=1000, gas_price=1_200_000_000)
    with pytest.raises(SignedTxInvalidError):
        await handler.replace(tx_id, token, raw, mode="rbf")


@pytest.mark.asyncio
async def test_replace_rejects_non_stuck(
    session_factory, org_id, make_account, seed_transaction, sign_tx
) -> None:
    account = make_account()
    tx_id = seed_transaction(org_id=org_id, wallet=account.address, status="approved")
    handler = _handler(session_factory)
    token = handler._tokens.issue(tx_id)  # noqa: SLF001
    raw = sign_tx(account, nonce=0, to="0x" + "2" * 40, value=1000, gas_price=1_200_000_000)
    with pytest.raises(DecisionNotApprovedError):
        await handler.replace(tx_id, token, raw, mode="rbf")


@pytest.mark.asyncio
async def test_replace_single_use_token(
    session_factory, org_id, make_account, seed_transaction, sign_tx
) -> None:
    account = make_account()
    tx_id = _make_stuck(session_factory, org_id, account.address, seed_transaction)
    handler = _handler(session_factory)
    token = handler._tokens.issue(tx_id)  # noqa: SLF001
    raw = sign_tx(account, nonce=0, to="0x" + "2" * 40, value=1000, gas_price=1_200_000_000)
    await handler.replace(tx_id, token, raw, mode="rbf")
    with pytest.raises(TokenConsumedError):
        await handler.replace(tx_id, token, raw, mode="rbf")
