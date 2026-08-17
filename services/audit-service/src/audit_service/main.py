"""FastAPI app hosting the anchor batching worker + health endpoint.

Startup is fail-closed: if anchoring is configured, a missing/invalid piece
raises and the service refuses to boot (an operator must fix the config). If
anchoring is not configured at all (dev without a chain), the worker is
disabled and /healthz reports it.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from at_shared.config import get_settings
from at_shared.db import SessionLocal
from at_shared.schemas.tx import ChainId
from blockchain.config import ChainConfig
from fastapi import FastAPI

from audit_service.chain import AnchorChainClient
from audit_service.worker import DbAnchorWorker, SqlAlchemyBatchStore

logger = logging.getLogger("audit_service.main")


def build_worker() -> DbAnchorWorker | None:
    """Construct the durable worker from shared settings (None if disabled)."""
    settings = get_settings()
    if not settings.anchor_rpc_url:
        logger.warning("ANCHOR_RPC_URL unset; anchor worker disabled")
        return None
    chain = ChainConfig(ChainId.ETHEREUM, [settings.anchor_rpc_url], settings.anchor_confirmations)
    client = AnchorChainClient(
        chain=chain,
        contract=settings.anchor_contract_address,
        private_key=settings.anchor_wallet_private_key,
        eip155_chain_id=settings.anchor_chain_id,
        confirmations=settings.anchor_confirmations,
        gas_buffer_pct=settings.gas_buffer_pct,
    )
    store = SqlAlchemyBatchStore(SessionLocal)
    return DbAnchorWorker(
        store=store,
        chain=client,
        max_records=settings.anchor_batch_max_records,
        interval_seconds=settings.anchor_batch_interval_seconds,
        max_attempts=settings.anchor_max_attempts,
        backoff_base_seconds=settings.anchor_backoff_base_seconds,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    worker = build_worker()
    app.state.worker = worker
    task: asyncio.Task | None = None
    if worker is not None:
        task = asyncio.create_task(worker.run())
    try:
        yield
    finally:
        if task is not None:
            worker.stop()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


app = FastAPI(
    title="AgentThreshold Audit Service",
    description="Durable Merkle batching + on-chain audit anchoring (FR-AUDIT-01)",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/healthz")
async def healthz() -> dict[str, object]:
    worker: DbAnchorWorker | None = app.state.worker
    return {
        "status": "ok" if worker is not None else "disabled",
        "pending_records": worker.pending_count if worker is not None else 0,
        "last_anchored_batch_id": (
            worker.last_anchored_batch_id if worker is not None else None
        ),
    }