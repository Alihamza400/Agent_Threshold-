"""Normalize an unsigned EVM transaction into a ScreenRequest.

The SDK is NON-CUSTODIAL: it never holds a private key. The agent's own
signer (a callable) is invoked only after the pipeline approves. This module
only maps the unsigned transaction the agent is about to sign into the
canonical screening payload.
"""

from __future__ import annotations

from typing import Any, Protocol

from .errors import AgentThresholdError
from .schemas import ChainId, ScreenRequest

__all__ = ["Signer", "unsigned_tx_to_screen_request"]


class Signer(Protocol):
    """Anything callable that turns an unsigned tx into a signed one."""

    def __call__(self, unsigned_tx: dict[str, Any]) -> Any: ...


class InvalidUnsignedTxError(AgentThresholdError):
    """The unsigned transaction dict is missing required fields (fail-closed)."""


def _to_int(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise InvalidUnsignedTxError(f"'{name}' must be an integer or 0x-hex string, got bool")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.lower().startswith("0x"):
        try:
            return int(value, 16)
        except ValueError as exc:
            raise InvalidUnsignedTxError(
                f"'{name}' is not a valid 0x-hex integer: {value!r}"
            ) from exc
    raise InvalidUnsignedTxError(
        f"'{name}' must be an integer or 0x-hex string, got {type(value).__name__}"
    )


def unsigned_tx_to_screen_request(
    unsigned_tx: dict[str, Any],
    *,
    agent_id: str,
    chain_id: ChainId,
    task_context: str | None = None,
) -> ScreenRequest:
    """Map an unsigned EVM transaction dict to a canonical ScreenRequest.

    Accepts EVM-style keys (``from``, ``to``, ``value``, ``data``, ``gas``,
    ``gasPrice``) as ints or 0x-hex strings. ``from`` is required; anything
    else the gateway needs to see (token, etc.) can be passed via the
    ``**overrides``-style extras in the caller.
    """
    if not isinstance(unsigned_tx, dict):
        raise InvalidUnsignedTxError("unsigned_tx must be a dict")
    if "from" not in unsigned_tx:
        raise InvalidUnsignedTxError("unsigned tx is missing required field 'from'")
    if "value" not in unsigned_tx:
        raise InvalidUnsignedTxError("unsigned tx is missing required field 'value'")

    try:
        return ScreenRequest(
            agent_id=agent_id,
            chain_id=chain_id,
            from_address=unsigned_tx["from"],
            to_address=unsigned_tx.get("to"),
            value_wei=_to_int(unsigned_tx["value"], "value"),
            calldata=unsigned_tx.get("data"),
            gas_limit=_to_int(unsigned_tx["gas"], "gas")
            if unsigned_tx.get("gas") is not None
            else None,
            gas_price_wei=(
                _to_int(unsigned_tx["gasPrice"], "gasPrice")
                if unsigned_tx.get("gasPrice") is not None
                else None
            ),
            task_context=task_context,
        )
    except AgentThresholdError:
        raise
    except Exception as exc:  # noqa: BLE001 - surface any mapping failure as fail-closed
        raise InvalidUnsignedTxError(
            f"could not build screen request from unsigned tx: {exc}"
        ) from exc
