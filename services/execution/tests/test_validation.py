"""Signed-tx validation tests: integrity, nonce, gas ceiling, tamper."""

from __future__ import annotations

import pytest
from at_shared.models import Transaction
from execution_service.errors import (
    GasCeilingError,
    NonceMismatchError,
    SignedTxInvalidError,
)
from execution_service.validation import decode_signed_tx, validate_signed_tx


def _tx(session_factory, org_id, seed_transaction, **kw) -> Transaction:
    tx_id = seed_transaction(org_id=org_id, nonce=7, **kw)
    with session_factory() as s:
        return s.get(Transaction, tx_id)


def test_valid_signed_tx_passes(
    session_factory, org_id, make_account, seed_transaction, sign_tx
) -> None:
    account = make_account()
    tx = _tx(session_factory, org_id, seed_transaction, wallet=account.address)
    raw = sign_tx(account, nonce=7, to=tx.to_address)
    validate_signed_tx(tx, decode_signed_tx(raw), reserved_nonce=7)


def test_wrong_chain_rejected(
    session_factory, org_id, make_account, seed_transaction, sign_tx
) -> None:
    account = make_account()
    tx = _tx(session_factory, org_id, seed_transaction, wallet=account.address)
    raw = sign_tx(account, nonce=7, to=tx.to_address, chain_id=8454)
    with pytest.raises(SignedTxInvalidError):
        validate_signed_tx(tx, decode_signed_tx(raw), reserved_nonce=7)


def test_wrong_sender_rejected(
    session_factory, org_id, make_account, seed_transaction, sign_tx
) -> None:
    other = make_account()
    account = make_account()
    tx = _tx(session_factory, org_id, seed_transaction, wallet=account.address)
    raw = sign_tx(other, nonce=7, to=tx.to_address)
    with pytest.raises(SignedTxInvalidError):
        validate_signed_tx(tx, decode_signed_tx(raw), reserved_nonce=7)


def test_wrong_value_rejected(
    session_factory, org_id, make_account, seed_transaction, sign_tx
) -> None:
    account = make_account()
    tx = _tx(session_factory, org_id, seed_transaction, wallet=account.address)
    raw = sign_tx(account, nonce=7, to=tx.to_address, value=tx.value_wei + 1)
    with pytest.raises(SignedTxInvalidError):
        validate_signed_tx(tx, decode_signed_tx(raw), reserved_nonce=7)


def test_wrong_recipient_rejected(
    session_factory, org_id, make_account, seed_transaction, sign_tx
) -> None:
    account = make_account()
    tx = _tx(session_factory, org_id, seed_transaction, wallet=account.address)
    raw = sign_tx(account, nonce=7, to="0x" + "3" * 40)
    with pytest.raises(SignedTxInvalidError):
        validate_signed_tx(tx, decode_signed_tx(raw), reserved_nonce=7)


def test_wrong_nonce_rejected(
    session_factory, org_id, make_account, seed_transaction, sign_tx
) -> None:
    account = make_account()
    tx = _tx(session_factory, org_id, seed_transaction, wallet=account.address)
    raw = sign_tx(account, nonce=8, to=tx.to_address)  # reserved nonce is 7
    with pytest.raises(NonceMismatchError):
        validate_signed_tx(tx, decode_signed_tx(raw), reserved_nonce=7)


def test_gas_over_ceiling_rejected(
    session_factory, org_id, make_account, seed_transaction, sign_tx
) -> None:
    account = make_account()
    tx = _tx(session_factory, org_id, seed_transaction, wallet=account.address, gas_limit=21000)
    raw = sign_tx(account, nonce=7, to=tx.to_address, gas=50000)
    with pytest.raises(GasCeilingError):
        validate_signed_tx(tx, decode_signed_tx(raw), reserved_nonce=7)


def test_garbage_raw_rejected() -> None:
    with pytest.raises(SignedTxInvalidError):
        decode_signed_tx("not-hex")
    with pytest.raises(SignedTxInvalidError):
        decode_signed_tx("0xzz")
