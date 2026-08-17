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
from at_shared.schemas.tx import ChainId
from blockchain.config import ChainConfig
from fastapi import FastAPI

from audit_service.batcher import AnchorBatcher
from audit_service.chain import AnchorChainClient

logger = logging.getLogger("audit_service.main")


def build_batcher() -> AnchorBatcher | None:
    """Construct the batcher from shared settings (None if anchoring disabled)."""
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
    return AnchorBatcher(
        chain=client,
        max_records=settings.anchor_batch_max_records,
        interval_seconds=settings.anchor_batch_interval_seconds,
        max_attempts=settings.anchor_max_attempts,
        backoff_base_seconds=settings.anchor_backoff_base_seconds,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    batcher = build_batcher()
    app.state.batcher = batcher
    task: asyncio.Task | None = None
    if batcher is not None:
        task = asyncio.create_task(batcher.run())
    try:
        yield
    finally:
        if task is not None:
            batcher.stop()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


app = FastAPI(
    title="AgentThreshold Audit Service",
    description="Async Merkle batching + on-chain audit anchoring (FR-AUDIT-01)",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/healthz")
async def healthz() -> dict[str, object]:
    batcher: AnchorBatcher | None = app.state.batcher
    return {
        "status": "ok" if batcher is not None else "disabled",
        "pending_records": batcher.pending_count if batcher is not None else 0,
        "last_anchored_batch_id": (
            batcher.last_anchored_batch_id if batcher is not None else None
        ),
    }