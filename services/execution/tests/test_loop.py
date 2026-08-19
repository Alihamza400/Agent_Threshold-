"""Worker loop tests: tick composition + fault tolerance."""

from __future__ import annotations

import asyncio

import pytest
from execution_service.monitor import ConfirmMonitor
from execution_service.worker import ExecutionWorker
from helpers_exec import FakeRPC


class FailingMonitor:
    async def confirm_broadcasts(self):
        raise RuntimeError("boom")

    async def detect_reorgs(self):
        raise RuntimeError("boom")


@pytest.mark.asyncio
async def test_tick_reports_counts(session_factory, org_id, make_account, seed_transaction) -> None:
    account = make_account()
    seed_transaction(org_id=org_id, wallet=account.address, status="broadcast")
    monitor = ConfirmMonitor(
        session_factory=session_factory,
        chain_resolver=lambda _c: None,  # no RPC -> no-op
        rpc_factory=lambda _c: FakeRPC(),
    )
    worker = ExecutionWorker(
        monitor=monitor,
        session_factory=session_factory,
        stuck_after_seconds=0.0,
    )
    result = await worker.tick()
    assert set(result) == {"executed", "reorged", "stuck"}


@pytest.mark.asyncio
async def test_run_loop_survives_faults() -> None:
    worker = ExecutionWorker(
        monitor=FailingMonitor(),
        session_factory=None,
        sleep=lambda s: asyncio.sleep(0),
    )
    task = asyncio.create_task(worker.run(poll_seconds=0.0))
    await asyncio.sleep(0.05)  # several ticks all raise; loop must keep going
    assert not task.done()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
