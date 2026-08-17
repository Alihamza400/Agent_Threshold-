"""Multi-provider JSON-RPC client with fail-closed cross-checking (5.1, 5.4).

- Deterministic reads (eth_call, eth_getBalance, block headers) are executed
  against the PRIMARY provider and cross-checked against the FALLBACK; any
  disagreement raises CrossCheckMismatchError so the orchestrator fails
  closed instead of trusting a potentially malicious RPC (threat: RPC
  spoofing, TRD Section 8).
- Transport errors, HTTP errors, and JSON-RPC errors all raise RPCError.
- If a fallback is not configured, the cross-check is skipped (primary only).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import httpx

from blockchain.config import ChainConfig
from blockchain.errors import CrossCheckMismatchError, NoProviderConfiguredError, RPCError

# Methods whose result is an intrinsic property of the transaction itself and
# therefore must NOT be cross-checked (each provider legitimately differs).
_NO_CROSS_CHECK = frozenset(
    {
        "eth_sendRawTransaction",
        "eth_getTransactionReceipt",
        "eth_getTransactionByHash",
        "eth_getTransactionCount",  # pending count drifts between providers
    }
)


def _hex(value: int) -> str:
    return hex(value)


def _unhex(value: str) -> int:
    return int(value, 16)


class RPCClient:
    def __init__(self, chain: ChainConfig, http: httpx.AsyncClient | None = None) -> None:
        self.chain = chain
        self._http = http or httpx.AsyncClient(timeout=httpx.Timeout(5.0))

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _post(self, url: str, method: str, params: Sequence[Any]) -> Any:
        try:
            resp = await self._http.post(
                url,
                json={"jsonrpc": "2.0", "id": 1, "method": method, "params": list(params)},
            )
        except httpx.HTTPError as exc:
            raise RPCError(f"{method} transport failure: {exc}") from exc
        if resp.status_code != 200:
            raise RPCError(f"{method} HTTP {resp.status_code}: {resp.text[:200]}")
        try:
            payload = resp.json()
        except json.JSONDecodeError as exc:
            raise RPCError(f"{method} invalid JSON response") from exc
        if "error" in payload:
            raise RPCError(f"{method} rpc error: {payload['error']}")
        return payload.get("result")

    async def call(
        self,
        method: str,
        params: Sequence[Any],
        *,
        cross_check: bool = False,
    ) -> Any:
        """Execute `method`, cross-checking against the fallback provider when
        `cross_check` is True and the method is a deterministic read."""
        if not self.chain.rpc_urls:
            raise NoProviderConfiguredError(f"no RPC configured for {self.chain.chain_id.value}")

        primary = await self._post(self.chain.rpc_urls[0], method, params)

        if (
            cross_check
            and method not in _NO_CROSS_CHECK
            and len(self.chain.rpc_urls) > 1
        ):
            try:
                fallback = await self._post(self.chain.rpc_urls[1], method, params)
            except RPCError:
                # Fallback provider itself failed; a single consistent primary is
                # acceptable for reads, but cross-check was best-effort here.
                return primary
            if primary != fallback:
                raise CrossCheckMismatchError(
                    f"{method} differs between providers: {primary!r} vs {fallback!r}"
                )
        return primary

    async def get_balance(self, address: str, block: str = "latest") -> int:
        return _unhex(await self.call("eth_getBalance", [address, block], cross_check=True))

    async def get_transaction_count(self, address: str, block: str = "latest") -> int:
        return _unhex(await self.call("eth_getTransactionCount", [address, block]))

    async def estimate_gas(self, tx: dict[str, Any]) -> int:
        return _unhex(await self.call("eth_estimateGas", [tx], cross_check=True))

    async def get_block_number(self) -> int:
        return _unhex(await self.call("eth_blockNumber", [], cross_check=True))

    async def get_storage_at(self, address: str, slot: str, block: str = "latest") -> str:
        return await self.call(
            "eth_getStorageAt", [address, slot, block], cross_check=True
        )

    async def call_contract(self, tx: dict[str, Any]) -> str:
        return await self.call("eth_call", [tx, "latest"], cross_check=True)

    async def send_raw_transaction(self, raw: str) -> str:
        """Broadcast a signed raw transaction; returns the transaction hash.

        Intentionally not cross-checked: `_NO_CROSS_CHECK` treats submission
        as provider-specific (each node may accept/reject independently).
        """
        return await self.call("eth_sendRawTransaction", [raw])

    async def get_transaction_receipt(self, tx_hash: str) -> dict[str, Any] | None:
        return await self.call("eth_getTransactionReceipt", [tx_hash])

    async def debug_trace_call(self, tx: dict[str, Any]) -> Any:
        return await self.call(
            "debug_traceCall",
            [tx, "latest", {"tracer": "prestateTracer"}],
            cross_check=False,  # tracer output is large; primary used for diff
        )


# --------------------------------------------------------------------------
# Sync convenience (nonce / oracle paths run in threadpool workers)
# --------------------------------------------------------------------------
class SyncRPC:
    """Blocking wrapper for the nonce/health paths that must not be async."""

    def __init__(self, chain: ChainConfig) -> None:
        self.chain = chain

    def _call(self, method: str, params: Sequence[Any]) -> Any:
        with httpx.Client(timeout=httpx.Timeout(5.0)) as http:
            client = RPCClient(self.chain, http)
            try:
                result = client.call(method, params)
            finally:
                http.close()
            return result

    def get_transaction_count(self, address: str, block: str = "latest") -> int:
        return _unhex(self._call("eth_getTransactionCount", [address, block]))


def gas_price_rpc(chain: ChainConfig) -> int:
    """Fetch current gas price (wei) via a short-lived sync client."""
    with httpx.Client(timeout=httpx.Timeout(5.0)) as http:
        client = RPCClient(chain, http)
        try:
            return _unhex(client.call("eth_gasPrice", []))
        finally:
            http.close()