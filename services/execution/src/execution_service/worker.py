"""Execution worker loop (task 8.5).

Per tick, in order:
  1. confirm broadcasts (receipts to chain depth) -> executed
  2. flag reorgs among recently confirmed -> reorged
  3. flag stuck broadcasts -> stuck (RBF/cancel re-screen via API)

The loop must survive any transient fault: exceptions are logged and the next
tick proceeds. Fail-closed by construction — nothing here can broadcast
without a fresh single-use token and a conditional DB transition.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from at_shared.db import get_session_factory

from execution_service.monitor import ConfirmMonitor
from execution_service.rbf import flag_stuck

logger = logging.getLogger("execution_service.worker")


@dataclass
class ExecutionWorker:
    monitor: ConfirmMonitor
    session_factory: Callable = field(default=get_session_factory)
    stuck_after_seconds: float = 60.0
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep

    async def tick(self) -> dict[str, int]:
        executed = await self.monitor.confirm_broadcasts()
        reorged = len(await self.monitor.detect_reorgs())
        stuck = len(flag_stuck(self.session_factory, stuck_after_seconds=self.stuck_after_seconds))
        return {"executed": executed, "reorged": reorged, "stuck": stuck}

    async def run(self, poll_seconds: float = 1.0) -> None:
        while True:
            try:
                await self.tick()
            except Exception:  # noqa: BLE001 - the loop must survive transient faults
                logger.exception("execution worker tick failed")
            await self.sleep(poll_seconds)


def build_monitor(
    *,
    session_factory=None,
    chain_resolver=None,
    rpc_factory=None,
) -> ConfirmMonitor:
    """Wire the monitor from settings (used by the service entrypoint)."""
    from blockchain.config import load_chain_configs
    from blockchain.rpc import RPCClient

    session_factory = session_factory or get_session_factory()
    chains = load_chain_configs()

    def resolve(chain_id: str) -> object | None:
        try:
            from at_shared.schemas.tx import ChainId

            return chains.get(ChainId(chain_id))
        except ValueError:
            return None

    return ConfirmMonitor(
        session_factory=session_factory,
        chain_resolver=chain_resolver or resolve,  # type: ignore[arg-type]
        rpc_factory=rpc_factory or RPCClient,
    )
