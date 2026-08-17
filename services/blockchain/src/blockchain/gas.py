"""Gas estimation + policy ceiling validation (FR-CHAIN-02).

- Estimates gas via eth_estimateGas.
- Applies the configured safety buffer (default 20%) on top.
- Compares against the policy gas ceiling; exceeding it raises
  GasExceedsCeilingError BEFORE anything is broadcast.
"""

from __future__ import annotations

from at_shared.config import get_settings

from blockchain.errors import GasExceedsCeilingError
from blockchain.rpc import RPCClient


def gas_with_buffer(estimated: int, buffer_pct: float | None = None) -> int:
    """Apply the safety buffer to a raw gas estimate (ceil to integer)."""
    pct = get_settings().gas_buffer_pct if buffer_pct is None else buffer_pct
    if pct < 0:
        raise ValueError("gas buffer cannot be negative")
    return estimated + (estimated * pct // 100)


def validate_gas_ceiling(estimated: int, ceiling: int | None) -> bool:
    """True when the estimate stays under the policy ceiling (or ceiling unset)."""
    if ceiling is None:
        return True
    return estimated <= ceiling


async def estimate_and_check(
    client: RPCClient,
    tx: dict,
    *,
    ceiling: int | None,
    buffer_pct: float | None = None,
) -> tuple[int, bool]:
    """Estimate gas with buffer and validate against the policy ceiling.

    Returns (gas_with_buffer, ceiling_used). Raises GasExceedsCeilingError
    when the buffered estimate exceeds the ceiling (fail-closed).
    """
    raw = await client.estimate_gas(tx)
    buffered = gas_with_buffer(raw, buffer_pct)
    ceiling_used = not validate_gas_ceiling(buffered, ceiling)
    if ceiling_used:
        raise GasExceedsCeilingError(buffered, ceiling or 0)
    return buffered, False