"""Screening API (TRD FR-API-01, FR-ORCH-01, FR-ORCH-02, FR-ADMIN-02).

The screen endpoint delegates the full pipeline to the Phase 8 orchestrator
(fail-closed engine: kill-switch -> policy -> classifier -> simulation ->
anomaly -> policy -> confidence -> persist). The gateway owns authN/authZ,
rate limiting, and the admin kill-switch; the orchestrator owns screening.

Any orchestrator failure fails closed (block/escalate) — never a silent
auto-approve (SR-04, TRD 4.9/4.10).
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.deps import get_api_key_context, require_admin, require_auditor_or_above
from at_shared.db import get_db
from at_shared.models import Agent, Transaction
from at_shared.schemas.auth import CurrentUser
from at_shared.schemas.tx import Decision, DecisionType, ScreenRequest, TransactionRead
from at_shared.uuid7 import uuid7
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from orchestrator.pipeline import Pipeline
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

router = APIRouter(prefix="/v1", tags=["transactions"])

# Fail-closed screening pipeline (Phase 8 orchestrator), one per worker. The
# pipeline owns the LLM clients/circuit breakers, simulation, and persistence.
_pipeline = Pipeline()


class KillSwitchBody(BaseModel):
    scope: str = Field(pattern=r"^(agent|org)$")
    agent_id: str | None = None
    reason: str = Field(default="", max_length=500)


def _fail_closed(reason: str) -> Decision:
    """Fail-closed decision: block/escalate, never auto-approve (SR-04)."""
    return Decision(
        decision=DecisionType.REJECT,
        reasons=[reason],
        confidence=0.0,
        risk_summary=f"Screening unavailable: {reason}",
    )


@router.post("/transactions/screen", response_model=Decision)
async def screen_transaction(
    body: ScreenRequest,
    request: Request,
    api_ctx: dict = Depends(get_api_key_context),
) -> Decision:
    """Delegate the full screening pipeline to the orchestrator (8.3).

    The gateway enforces the API-key scope here; the orchestrator re-checks
    org scope and owns every pipeline stage. Any backend failure fails closed
    (SR-04) — the gateway never runs a screening path of its own.
    """
    trace_id = request.headers.get("x-trace-id") or uuid7()

    # ---- API key scope (FR-AUTH-01) — fail-closed on mismatch ------------
    if api_ctx["agent_ids"] and body.agent_id not in api_ctx["agent_ids"]:
        return _fail_closed("agent not in API key scope")

    # ---- pipeline delegation ---------------------------------------------
    try:
        result = await _pipeline.screen(body, org_id=api_ctx["org_id"], trace_id=trace_id)
    except Exception as exc:  # noqa: BLE001 - backend failure must fail closed
        return _fail_closed(f"screening pipeline unavailable: {exc}")
    return result.decision


@router.get("/transactions/{transaction_id}", response_model=TransactionRead)
def get_transaction(
    transaction_id: str,
    db: Session = Depends(get_db),
    api_ctx: dict = Depends(get_api_key_context),
) -> TransactionRead:
    tx = db.get(Transaction, transaction_id)
    if tx is None or tx.org_id != api_ctx["org_id"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Transaction not found")
    return TransactionRead.model_validate(tx)


@router.get("/agents/{agent_id}/history", response_model=list[TransactionRead])
def agent_history(
    agent_id: str,
    limit: int = 50,
    db: Session = Depends(get_db),
    api_ctx: dict = Depends(get_api_key_context),
) -> list[TransactionRead]:
    rows = db.scalars(
        select(Transaction)
        .where(Transaction.agent_id == agent_id, Transaction.org_id == api_ctx["org_id"])
        .order_by(Transaction.created_at.desc())
        .limit(min(max(limit, 1), 500))
    ).all()
    return [TransactionRead.model_validate(t) for t in rows]


# --------------------------------------------------------------------------
# Dashboard / auditor reads (JWT, org-scoped)
# --------------------------------------------------------------------------
@router.get("/transactions", response_model=list[TransactionRead])
def list_transactions(
    agent_id: str | None = None,
    decision: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_auditor_or_above),
) -> list[TransactionRead]:
    """Org-wide transaction search for the dashboard (auditor and above)."""
    if decision is not None and decision not in {"approve", "reject", "escalate"}:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid decision filter")
    stmt = select(Transaction).where(Transaction.org_id == user.org_id)
    if agent_id:
        stmt = stmt.where(Transaction.agent_id == agent_id)
    if decision:
        stmt = stmt.where(Transaction.decision == decision)
    rows = db.scalars(
        stmt.order_by(Transaction.created_at.desc())
        .offset(max(offset, 0))
        .limit(min(max(limit, 1), 500))
    ).all()
    return [TransactionRead.model_validate(t) for t in rows]


# --------------------------------------------------------------------------
# Kill-switch (FR-ADMIN-02) — Admin only, SSO
# --------------------------------------------------------------------------
@router.post("/kill-switch")
def kill_switch(
    body: KillSwitchBody,
    db: Session = Depends(get_db),
    admin: CurrentUser = Depends(require_admin),
) -> dict:
    scope = body.scope
    reason = body.reason
    if scope not in {"agent", "org"}:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "scope must be 'agent' or 'org'")

    now = datetime.now(UTC)
    if scope == "agent":
        agent = db.scalar(
            select(Agent).where(Agent.id == body.agent_id, Agent.org_id == admin.org_id)
        )
        if agent is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found")
        agent.halted = True
        agent.halt_reason = reason
        agent.halted_at = now
    else:
        # org-wide halt: halt every agent in the org (idempotent)
        agents = db.scalars(select(Agent).where(Agent.org_id == admin.org_id)).all()
        for a in agents:
            a.halted = True
            a.halt_reason = reason
            a.halted_at = now

    db.commit()
    return {"halted": True, "scope": scope, "effective_at": now.isoformat()}


@router.delete("/kill-switch")
def resume_kill_switch(
    scope: str = Query(..., pattern=r"^(agent|org)$"),
    agent_id: str | None = None,
    db: Session = Depends(get_db),
    admin: CurrentUser = Depends(require_admin),
) -> dict:
    """Clear the kill-switch (idempotent): resume an agent or the whole org."""
    now = datetime.now(UTC)
    if scope == "agent":
        if not agent_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "agent_id required for agent scope")
        agent = db.scalar(select(Agent).where(Agent.id == agent_id, Agent.org_id == admin.org_id))
        if agent is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found")
        agents = [agent]
    else:
        agents = db.scalars(select(Agent).where(Agent.org_id == admin.org_id)).all()

    for a in agents:
        a.halted = False
        a.halt_reason = None
        a.halted_at = None
    db.commit()
    return {"halted": False, "scope": scope, "effective_at": now.isoformat()}
