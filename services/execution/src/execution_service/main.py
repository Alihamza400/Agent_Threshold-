"""FastAPI app for the execution adapter (task 8.5).

Endpoints (all gated by the internal execution API key):
  POST /v1/execution/prepare            reserve nonce + mint single-use token
  POST /v1/execution/submit             validate + broadcast the signed tx
  POST /v1/execution/{id}/replace       stuck tx -> RBF/cancel (re-screened)
  POST /v1/execution/{id}/cancel        explicit cancel (revoke token)
  GET  /v1/execution/{id}               current execution status

The worker (confirm/reorg/stuck) runs as a lifespan task.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
from contextlib import asynccontextmanager

from at_shared.config import get_settings
from at_shared.db import get_session_factory
from at_shared.http_security import install_http_security
from at_shared.models import Transaction
from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field

from execution_service.errors import (
    DecisionNotApprovedError,
    ExecutionError,
    SignedTxInvalidError,
    TokenConsumedError,
)
from execution_service.executor import ExecutionAdapter
from execution_service.monitor import ConfirmMonitor
from execution_service.rbf import StuckTxHandler
from execution_service.tokens import DecisionTokenStore
from execution_service.worker import ExecutionWorker, build_monitor

logger = logging.getLogger("execution_service.main")


# ------------------------------------------------------------------ auth
def _require_key(
    x_execution_key: str | None = Header(default=None, alias="X-Execution-Key"),
) -> None:
    expected = get_settings().execution_api_key
    if not x_execution_key or not secrets.compare_digest(x_execution_key, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid execution API key")


# ------------------------------------------------------------------ schemas
class PrepareBody(BaseModel):
    transaction_id: str = Field(min_length=1, max_length=64)


class SubmitBody(BaseModel):
    transaction_id: str = Field(min_length=1, max_length=64)
    decision_token: str
    signed_raw: str


class ReplaceBody(BaseModel):
    decision_token: str
    signed_raw: str
    mode: str = Field(pattern="^(rbf|cancel)$")


# ------------------------------------------------------------------ wiring
def build_adapter(*, session_factory=None, tokens=None, nonce_allocator=None) -> ExecutionAdapter:
    from at_shared.schemas.tx import ChainId
    from blockchain.config import load_chain_configs
    from blockchain.nonce import NonceAllocator
    from blockchain.rpc import RPCClient

    settings = get_settings()
    session_factory = session_factory or get_session_factory()
    chains = load_chain_configs()

    def resolve(chain_id: str) -> object | None:
        try:
            return chains.get(ChainId(chain_id))
        except ValueError:
            return None

    return ExecutionAdapter(
        session_factory=session_factory,
        tokens=tokens or DecisionTokenStore(ttl_seconds=settings.decision_token_ttl_seconds),
        nonce_allocator=nonce_allocator or NonceAllocator(),
        chain_resolver=resolve,  # type: ignore[arg-type]
        rpc_factory=RPCClient,
        max_broadcast_attempts=settings.execution_max_broadcast_attempts,
        backoff_base_seconds=settings.execution_backoff_base_seconds,
    )


def build_rescreen() -> StuckTxHandler:
    from orchestrator.pipeline import Pipeline

    settings = get_settings()
    pipeline = Pipeline(session_factory=get_session_factory())

    async def rescreen(request, org_id):
        result = await pipeline.screen(request, org_id=org_id)
        return result.decision

    return StuckTxHandler(
        session_factory=get_session_factory(),
        tokens=DecisionTokenStore(ttl_seconds=settings.decision_token_ttl_seconds),
        chain_resolver=build_adapter()._chain_resolver,  # noqa: SLF001 - same process wiring
        rpc_factory=__import__("blockchain.rpc", fromlist=["RPCClient"]).RPCClient,
        rescreen=rescreen,
        rbf_gas_bump_pct=settings.execution_rbf_gas_bump_pct,
        cancel_gas_bump_pct=settings.execution_cancel_gas_bump_pct,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    monitor: ConfirmMonitor = build_monitor()
    worker = ExecutionWorker(
        monitor=monitor,
        session_factory=get_session_factory(),
        stuck_after_seconds=settings.execution_stuck_after_seconds,
    )
    app.state.worker = worker
    app.state.adapter = build_adapter()
    task = asyncio.create_task(worker.run(poll_seconds=settings.execution_poll_seconds))
    try:
        yield
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


app = FastAPI(
    title="AgentThreshold Execution Adapter",
    description="Single-use decision token + nonce lock + signed-tx broadcast + confirm/reorg/stuck (8.5)",
    version="0.1.0",
    lifespan=lifespan,
)

_esettings = get_settings()
install_http_security(
    app,
    max_body_bytes=_esettings.max_request_body_bytes,
    is_production=_esettings.is_production,
)


@app.get("/healthz")
async def healthz() -> dict[str, object]:
    return {"status": "ok"}


@app.post("/v1/execution/prepare")
async def prepare(body: PrepareBody, _: None = Depends(_require_key)) -> dict[str, object]:
    try:
        result = app.state.adapter.prepare(body.transaction_id)
    except DecisionNotApprovedError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except ExecutionError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    return {"transaction_id": body.transaction_id, **result.__dict__}


@app.post("/v1/execution/submit")
async def submit(body: SubmitBody, _: None = Depends(_require_key)) -> dict[str, object]:
    try:
        result = await app.state.adapter.submit(
            body.transaction_id, body.decision_token, body.signed_raw
        )
    except TokenConsumedError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except (SignedTxInvalidError, DecisionNotApprovedError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except ExecutionError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    return {"transaction_id": body.transaction_id, **result.__dict__}


@app.post("/v1/execution/{transaction_id}/replace")
async def replace(
    transaction_id: str, body: ReplaceBody, _: None = Depends(_require_key)
) -> dict[str, object]:
    handler = build_rescreen()
    try:
        result = await handler.replace(
            transaction_id, body.decision_token, body.signed_raw, mode=body.mode
        )
    except TokenConsumedError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except (SignedTxInvalidError, DecisionNotApprovedError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except ExecutionError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    return {"transaction_id": transaction_id, **result.__dict__}


@app.post("/v1/execution/{transaction_id}/cancel")
async def cancel(transaction_id: str, _: None = Depends(_require_key)) -> dict[str, object]:
    try:
        app.state.adapter.cancel(transaction_id)
    except DecisionNotApprovedError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except ExecutionError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    return {"transaction_id": transaction_id, "status": "cancelled"}


@app.get("/v1/execution/{transaction_id}")
async def execution_status(
    transaction_id: str, _: None = Depends(_require_key)
) -> dict[str, object]:
    with get_session_factory() as session:
        tx = session.get(Transaction, transaction_id)
        if tx is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "transaction not found")
        return {
            "transaction_id": tx.id,
            "status": tx.status,
            "decision": tx.decision,
            "tx_hash": tx.tx_hash,
            "nonce": tx.nonce,
            "broadcast_at": tx.broadcast_at,
            "confirmed_at": tx.confirmed_at,
            "block_number": tx.block_number,
            "executed_at": tx.executed_at,
            "stuck_at": tx.stuck_at,
            "reorged_at": tx.reorged_at,
            "broadcast_attempts": tx.broadcast_attempts,
        }
