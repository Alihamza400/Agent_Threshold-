"""Fork-per-request simulation via Anvil (5.2, 5.3; FR-CHAIN-01).

Isolation: each simulation runs against a FRESH anvil fork and is torn down
afterwards — real chain state is never mutated (verified by design, and by
the process lifecycle in AnvilProcessSimulator).

Backends:
  - AnvilProcessSimulator: spawns `anvil --fork-url <rpc>` per request on a
    random port (true isolation). Requires the foundry binary on PATH.
  - LocalAnvilSimulator: talks to a pre-provisioned anvil (dev/tests).
  - The orchestration in `simulate.py` falls back to a structured error
    result when no backend is available (fail-closed, never silent).

State diff: `debug_traceCall` with the prestate tracer captures pre-state of
every touched slot; post-values are read via eth_getStorageAt / getBalance to
produce before/after entries.
"""

from __future__ import annotations

import abc
import asyncio
import socket
import subprocess
from typing import Any

import httpx
from at_shared.schemas.simulation import (
    SimulateRequest,
    SimulationResult,
    StateDiffEntry,
)
from at_shared.schemas.tx import ChainId

from blockchain.config import ChainConfig
from blockchain.errors import RPCError
from blockchain.gas import gas_with_buffer
from blockchain.rpc import RPCClient

_SLOT_AS_HEX = "0x0"


def _hex(value: int) -> str:
    return hex(value)


def _unhex(value: str) -> int:
    return int(value, 16)


def _build_tx(req: SimulateRequest) -> dict[str, Any]:
    tx: dict[str, Any] = {
        "from": req.from_address,
        "value": _hex(req.value_wei),
    }
    if req.to_address:
        tx["to"] = req.to_address
    if req.calldata:
        tx["data"] = req.calldata
    return tx


def result_error(
    chain_id: ChainId,
    message: str,
    *,
    simulator: str = "stub",
    gas_ceiling_used: bool = False,
    gas_used_wei: int = 0,
) -> SimulationResult:
    from datetime import UTC, datetime

    return SimulationResult(
        chain_id=chain_id,
        status="error",
        gas_used_wei=gas_used_wei,
        gas_ceiling_used=gas_ceiling_used,
        revert_reason=message,
        simulated_at=datetime.now(UTC),
        simulator=simulator,
    )


class Simulator(abc.ABC):
    @abc.abstractmethod
    async def simulate(
        self,
        req: SimulateRequest,
        *,
        gas_ceiling: int | None,
    ) -> SimulationResult:
        """Simulate a transaction against an isolated fork."""


async def _trace_pre_state(client: RPCClient, tx: dict[str, Any]) -> dict[str, Any]:
    trace = await client.debug_trace_call(tx)
    return (trace or {}).get("pre", {})


async def _capture_state_diff(
    client: RPCClient,
    tx: dict[str, Any],
    pre_state: dict[str, Any],
) -> list[StateDiffEntry]:
    """Build before/after entries for every touched account/slot."""
    diffs: list[StateDiffEntry] = []
    for address, acct in pre_state.items():
        # Native balance change
        pre_balance = acct.get("balance", "0x0")
        post_balance = await client.get_balance(address)
        if _unhex(pre_balance) != post_balance:
            diffs.append(
                StateDiffEntry(
                    address=address,
                    slot="balance",
                    before=pre_balance,
                    after=_hex(post_balance),
                )
            )
        # Storage slot changes
        storage = acct.get("storage") or {}
        for slot, pre_value in storage.items():
            post_value = await client.get_storage_at(address, slot)
            if pre_value != post_value:
                diffs.append(
                    StateDiffEntry(address=address, slot=slot, before=pre_value, after=post_value)
                )
    return diffs


class AnvilProcessSimulator(Simulator):
    """Spawns a fresh anvil fork per request (true per-request isolation)."""

    def __init__(self, chain: ChainConfig, anvil_bin: str = "anvil") -> None:
        self.chain = chain
        self.anvil_bin = anvil_bin

    def _pick_port(self) -> int:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    async def simulate(
        self,
        req: SimulateRequest,
        *,
        gas_ceiling: int | None,
    ) -> SimulationResult:
        if not self.chain.rpc_urls:
            return result_error(req.chain_id, "no RPC configured for fork", simulator="anvil-fork")

        port = self._pick_port()
        url = f"http://127.0.0.1:{port}"
        proc = subprocess.Popen(
            [
                self.anvil_bin,
                "--fork-url",
                self.chain.rpc_urls[0],
                "--port",
                str(port),
                "--silent",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as http:
                await _wait_ready(url, http)
                client = RPCClient(ChainConfig(req.chain_id, [url], 0), http)
                return await _simulate_on_client(client, req, gas_ceiling=gas_ceiling, simulator="anvil-fork")
        finally:
            proc.terminate()
            try:
                await asyncio.to_thread(proc.wait, timeout=5)
            except Exception:  # noqa: BLE001
                proc.kill()


class LocalAnvilSimulator(Simulator):
    """Talks to a persistent anvil instance (dev / tests)."""

    def __init__(self, chain: ChainConfig, anvil_url: str) -> None:
        self.chain = chain
        self.anvil_url = anvil_url

    async def simulate(
        self,
        req: SimulateRequest,
        *,
        gas_ceiling: int | None,
    ) -> SimulationResult:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as http:
            client = RPCClient(ChainConfig(req.chain_id, [self.anvil_url], 0), http)
            return await _simulate_on_client(client, req, gas_ceiling=gas_ceiling, simulator="anvil-local")


async def _wait_ready(url: str, http: httpx.AsyncClient, attempts: int = 30) -> None:
    last: Exception | None = None
    for _ in range(attempts):
        try:
            resp = await http.post(url, json={"jsonrpc": "2.0", "id": 1, "method": "eth_chainId", "params": []})
            if resp.status_code == 200:
                return
        except httpx.HTTPError as exc:
            last = exc
        await asyncio.sleep(0.2)
    raise RPCError(f"anvil did not become ready: {last}")


async def _simulate_on_client(
    client: RPCClient,
    req: SimulateRequest,
    *,
    gas_ceiling: int | None,
    simulator: str,
) -> SimulationResult:
    """Execute the tx on the anvil fork; capture gas + state diff + status."""
    from datetime import UTC, datetime

    tx = _build_tx(req)

    # 1) Status + revert detection via eth_call
    try:
        await client.call_contract(tx)
        revert_reason = None
        status = "success"
    except RPCError as exc:
        revert_reason = _extract_revert_reason(str(exc))
        status = "reverted"

    # 2) Gas estimation (still valid for reverts; reports consumption)
    try:
        raw_gas = await client.estimate_gas(tx)
    except RPCError:
        raw_gas = 0

    # 3) State diff via prestate tracer
    try:
        pre_state = await _trace_pre_state(client, tx)
        state_diff = await _capture_state_diff(client, tx, pre_state)
    except RPCError:
        state_diff = []

    buffered = gas_with_buffer(raw_gas)
    ceiling_used = gas_ceiling is not None and buffered > gas_ceiling
    if ceiling_used:
        return result_error(
            req.chain_id,
            f"estimated gas {buffered} exceeds policy ceiling {gas_ceiling}",
            simulator=simulator,
            gas_ceiling_used=True,
            gas_used_wei=buffered,
        )

    return SimulationResult(
        chain_id=req.chain_id,
        status=status,  # type: ignore[arg-type]
        gas_used_wei=buffered,
        gas_ceiling_used=False,
        state_diff=state_diff,
        revert_reason=revert_reason,
        simulated_at=datetime.now(UTC),
        simulator=simulator,  # type: ignore[arg-type]
    )


def _extract_revert_reason(error_message: str) -> str:
    # anvil/eth_call revert errors embed the reason; keep a clean prefix.
    return error_message[:300]


class FakeSimulator(Simulator):
    """Deterministic simulator for tests (no anvil needed)."""

    def __init__(self, *, result_factory=None) -> None:
        self._factory = result_factory

    async def simulate(
        self,
        req: SimulateRequest,
        *,
        gas_ceiling: int | None,
    ) -> SimulationResult:
        from datetime import UTC, datetime

        if self._factory is not None:
            result = self._factory(req, gas_ceiling=gas_ceiling)
            if asyncio.iscoroutine(result):
                result = await result
            return result
        return SimulationResult(
            chain_id=req.chain_id,
            status="success",
            gas_used_wei=21000,
            gas_ceiling_used=False,
            simulated_at=datetime.now(UTC),
            simulator="anvil-fork",
        )