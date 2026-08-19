"""Signed-transaction integrity validation (task 8.5, TRD 5.3/5.8).

The Execution Adapter is non-custodial: the agent signs with its own key
infrastructure and submits the signed raw transaction. Before broadcast we
verify the signed payload is EXACTLY the transaction that was screened and
approved — an attacker who obtains a decision token must not be able to
broadcast a different payload under it.

Checks (all must pass, else SignedTxInvalidError / subclass):
  - chainId matches the screened chain (EIP-155).
  - `from` == the agent's registered wallet.
  - `to` / `value` / calldata match the approved transaction row.
  - nonce == the Redis-locked reservation (NonceMismatchError).
  - gas does not exceed the screened gas ceiling (GasCeilingError).
"""

from __future__ import annotations

import rlp
from at_shared.models import Transaction
from at_shared.schemas.tx import ChainId
from eth_account import Account
from eth_account._utils.legacy_transactions import Transaction as LegacyTx
from eth_account.typed_transactions import TypedTransaction

from execution_service.errors import (
    GasCeilingError,
    NonceMismatchError,
    SignedTxInvalidError,
)

# EIP-155 chain ids for the chains we support (ChainId enum -> integer).
CHAIN_IDS: dict[ChainId, int] = {
    ChainId.ETHEREUM: 1,
    ChainId.BASE: 8453,
    ChainId.ARBITRUM: 42161,
}

_TYPED_TYPES = (0x02, 0x03, 0x04)  # EIP-1559 / EIP-4844 / EIP-7702


def _norm_data(data) -> str:
    if data is None:
        return "0x"
    if isinstance(data, str):
        return data.lower()
    return "0x" + bytes(data).hex().lower()


def _norm_to(to) -> str | None:
    if to is None or to == b"" or to == "":
        return None
    if isinstance(to, str):
        return to.lower()
    return "0x" + bytes(to).hex().lower()


def decode_signed_tx(signed_raw: str) -> dict:
    """Decode a signed raw transaction into a canonical field dict.

    Handles legacy (EIP-155) and typed (EIP-2930/1559/4844/7702) transactions.
    The sender is recovered from the signature. Any decode failure raises
    SignedTxInvalidError (rejectable input).
    """
    if not isinstance(signed_raw, str) or not signed_raw.lower().startswith("0x"):
        raise SignedTxInvalidError("signed_raw must be a 0x-prefixed hex string")
    try:
        raw = bytes.fromhex(signed_raw[2:])
        sender = Account.recover_transaction(signed_raw).lower()
        if raw and raw[0] in _TYPED_TYPES:
            d = TypedTransaction.from_bytes(raw).as_dict()
            return {
                "from": sender,
                "chainId": int(d.get("chainId") or 0),
                "nonce": int(d["nonce"]),
                "gas": int(d["gas"]),
                "gasPrice": int(d.get("gasPrice") or d.get("maxFeePerGas") or 0),
                "maxFeePerGas": int(d.get("maxFeePerGas") or 0),
                "to": _norm_to(d.get("to")),
                "value": int(d.get("value") or 0),
                "data": _norm_data(d.get("data")),
            }
        legacy = rlp.decode(raw, LegacyTx)
        return {
            "from": sender,
            "chainId": (int(legacy.v) - 35) // 2 if int(legacy.v) >= 35 else 0,
            "nonce": int(legacy.nonce),
            "gas": int(legacy.gas),
            "gasPrice": int(legacy.gasPrice),
            "maxFeePerGas": None,  # legacy tx has no EIP-1559 fee cap
            "to": _norm_to(legacy.to),
            "value": int(legacy.value),
            "data": _norm_data(legacy.data),
        }
    except SignedTxInvalidError:
        raise
    except Exception as exc:  # noqa: BLE001 - any decode failure is rejectable input
        raise SignedTxInvalidError(f"cannot decode signed transaction: {exc}") from exc


def validate_signed_tx(
    tx: Transaction,
    decoded: dict,
    *,
    reserved_nonce: int | None,
) -> None:
    """Raise the specific error when the signed payload diverges from the
    screened-and-approved transaction."""
    try:
        chain_id = ChainId(tx.chain_id)
    except ValueError as exc:
        raise SignedTxInvalidError(f"unsupported chain {tx.chain_id!r}") from exc
    if chain_id not in CHAIN_IDS:
        raise SignedTxInvalidError(f"no EIP-155 chain id for {chain_id.value}")
    if int(decoded.get("chainId") or 0) != CHAIN_IDS[chain_id]:
        raise SignedTxInvalidError("signed chainId does not match screened chain")

    sender = (decoded.get("from") or "").lower()
    if sender != tx.from_address.lower():
        raise SignedTxInvalidError(
            f"signed `from` {sender!r} does not match agent wallet {tx.from_address!r}"
        )

    signed_to = decoded.get("to")
    if signed_to != (tx.to_address.lower() if tx.to_address else None):
        raise SignedTxInvalidError("signed `to` does not match screened transaction")

    signed_value = int(decoded.get("value") or 0)
    if signed_value != tx.value_wei:
        raise SignedTxInvalidError("signed value does not match screened transaction")

    if _norm_data(decoded.get("data")) != _norm_data(tx.calldata):
        raise SignedTxInvalidError("signed calldata does not match screened transaction")

    signed_nonce = int(decoded.get("nonce"))
    if reserved_nonce is not None and signed_nonce != reserved_nonce:
        raise NonceMismatchError(f"signed nonce {signed_nonce} != reserved nonce {reserved_nonce}")

    signed_gas = int(decoded.get("gas") or 0)
    if tx.gas_limit is not None and signed_gas > tx.gas_limit:
        raise GasCeilingError(f"signed gas {signed_gas} exceeds screened ceiling {tx.gas_limit}")
