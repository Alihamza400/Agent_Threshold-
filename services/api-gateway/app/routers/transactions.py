"""Screening API (TRD FR-API-01, FR-ORCH-01, FR-ORCH-02, FR-ADMIN-02).

Phase 3 pipeline (deterministic + advisory AI):
  step 0: kill-switch check (fail-closed, checked FIRST)
  step 1: resolve agent + active policy
  step 2: intent classifier (advisory, LLM, bounded timeout, fail-closed)
  step 3: anomaly score against rolling baseline (deterministic)
  step 4: deterministic policy evaluation
  step 5: persist decision + return Decision object

LLM stages are advisory and schema-validated; any failure/timeout fails
closed (block/escalate) — never a silent auto-approve (TRD 4.9, 4.10).
Simulation (Phase 5) inserts after step 2.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.baseline_service import refresh_baseline
from app.deps import get_api_key_context, require_admin
from app.screening_context import build_screening_context
from at_shared.db import get_db
from at_shared.models import Agent, Policy, Transaction
from at_shared.schemas.auth import CurrentUser
from at_shared.schemas.tx import Decision, DecisionType, ScreenRequest, TransactionRead
from at_shared.uuid7 import uuid7
from fastapi import APIRouter, Depends, HTTPException, Request, status
from policy_engine.engine import PolicyData, evaluate
from pydantic import BaseModel, Field
from screening_agents.classifier import IntentClassifier
from screening_agents.llm import get_llm_client
from sqlalchemy import select
from sqlalchemy.orm import Session

router = APIRouter(prefix="/v1", tags=["transactions"])

# LLM client is created once per process; circuit breaker is shared per worker.
_llm = get_llm_client()
_classifier = IntentClassifier(_llm)


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


def _get_active_policy(db: Session, agent_id: str) -> Policy | None:
    return db.scalar(
        select(Policy)
        .where(Policy.agent_id == agent_id, Policy.is_active.is_(True))
        .order_by(Policy.version.desc())
        .limit(1)
    )


def _classify_intent(body: ScreenRequest) -> str | None:
    """Run the advisory Intent Classifier; return a scope note or None.

    Any LLM failure is caught here and treated as 'advisory unavailable' —
    the deterministic policy engine still decides. This does NOT weaken
    fail-closed semantics: the LLM is advisory and cannot approve anything.
    """
    try:
        result = _classifier.classify(body.task_context)
        return f"intent={result.action_class.value} conf={result.confidence:.2f}"
    except Exception:  # noqa: BLE001 - advisory stage must never break screening
        return None


@router.post("/transactions/screen", response_model=Decision)
def screen_transaction(
    body: ScreenRequest,
    request: Request,
    db: Session = Depends(get_db),
    api_ctx: dict = Depends(get_api_key_context),
) -> Decision:
    trace_id = request.headers.get("x-trace-id") or uuid7()

    # ---- step 0: kill-switch (FR-ADMIN-02) — checked first, fail-closed ----
    agent = db.scalar(select(Agent).where(Agent.id == body.agent_id))
    if agent is None or agent.org_id != api_ctx["org_id"]:
        return _fail_closed("agent not found for this key scope")
    if api_ctx["agent_ids"] and body.agent_id not in api_ctx["agent_ids"]:
        return _fail_closed("agent not in API key scope")
    if agent.halted:
        return Decision(
            decision=DecisionType.REJECT,
            reasons=[f"agent halted: {agent.halt_reason or 'kill-switch active'}"],
            confidence=0.0,
            risk_summary="Kill-switch is active for this agent",
        )

    # ---- step 1: active policy ----
    policy = _get_active_policy(db, body.agent_id)
    if policy is None:
        return _fail_closed("no active policy for agent")

    # ---- step 2: advisory intent classifier (bounded, fail-closed on error) --
    intent_note = _classify_intent(body)

    # ---- step 3: engine context + anomaly score (rolling baseline) ----
    # USD normalization requires an oracle (Phase 5); MVP uses value_wei/1e18
    # as a conservative proxy so limits still gate large transfers.
    context = build_screening_context(
        db,
        body.agent_id,
        to_address=body.to_address,
        value_wei=body.value_wei,
        usd_value=float(body.value_wei) / 1e18,
    )

    # ---- step 4: deterministic policy evaluation (anomaly is advisory) ----
    result = evaluate(
        PolicyData.from_orm(policy),
        to_address=body.to_address,
        value_wei=body.value_wei,
        gas_ceiling_used=body.gas_limit,
        ctx=context.engine_ctx,
    )
    reasons = list(result.reasons)
    if intent_note:
        reasons.append(intent_note)

    # ---- step 5: persist decision (audit trail) ----
    tx = Transaction(
        id=uuid7(),
        agent_id=body.agent_id,
        org_id=api_ctx["org_id"],
        chain_id=body.chain_id.value,
        from_address=body.from_address,
        to_address=body.to_address,
        value_wei=body.value_wei,
        usd_value=context.engine_ctx.usd_value,
        token=body.token,
        calldata=body.calldata,
        gas_limit=body.gas_limit,
        gas_price_wei=body.gas_price_wei,
        raw_params=body.model_dump(),
        decision=result.decision.value,
        confidence=0.0,
        risk_summary="; ".join(reasons) if reasons else "within policy",
        reasons=reasons,
        policy_version=result.policy_version,
        status="screened",
        trace_id=trace_id,
    )
    db.add(tx)
    db.commit()
    db.refresh(tx)

    # keep the behavioral baseline current (FR-DATA-02)
    refresh_baseline(db, body.agent_id)

    return Decision(
        decision=result.decision,
        reasons=reasons,
        confidence=0.0,
        risk_summary="; ".join(reasons) if reasons else "within policy",
        policy_version=result.policy_version,
        transaction_id=tx.id,
    )


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
        agent = db.scalar(select(Agent).where(Agent.id == body.agent_id, Agent.org_id == admin.org_id))
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