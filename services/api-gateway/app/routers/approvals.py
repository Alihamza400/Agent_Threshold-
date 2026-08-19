"""Escalation / approval queue (Phase 7.3).

GET  /v1/approvals?status=pending     queue (approver + admin)
POST /v1/approvals/{id}/approve       human approve -> tx status approved
POST /v1/approvals/{id}/reject        human reject  -> tx status rejected

Rules:
  * Only pending escalations can be decided; a second decision returns 409.
  * Overdue pending escalations auto-expire to `expired` (default reject,
    fail-closed) on read and before any decision attempt.
  * The decision is written atomically with the transaction status transition.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.deps import require_roles
from at_shared.db import get_db
from at_shared.models import Agent, Approval, Transaction
from at_shared.schemas.approval import ApprovalDecisionBody, ApprovalRead
from at_shared.schemas.auth import CurrentUser
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

router = APIRouter(prefix="/v1/approvals", tags=["approvals"])

# Human review is admin + approver (auditors are read-only by design).
require_reviewer = require_roles("admin", "approver")


def _expire_overdue(db: Session, org_id: str) -> None:
    """Transition overdue pending escalations to expired (fail-closed)."""
    now = datetime.now(UTC)
    overdue = db.scalars(
        select(Approval).where(
            Approval.org_id == org_id,
            Approval.status == "pending",
            Approval.expires_at.is_not(None),
            Approval.expires_at < now,
        )
    ).all()
    if overdue:
        for a in overdue:
            a.status = "expired"
            tx = db.get(Transaction, a.transaction_id)
            if tx is not None:
                tx.status = "rejected"
        db.commit()


def _get_pending(db: Session, approval_id: str, org_id: str) -> Approval:
    _expire_overdue(db, org_id)
    approval = db.scalar(
        select(Approval).where(Approval.id == approval_id, Approval.org_id == org_id)
    )
    if approval is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Approval not found")
    return approval


def _to_read(db: Session, approval: Approval) -> ApprovalRead:
    agent = db.get(Agent, approval.agent_id)
    tx = db.get(Transaction, approval.transaction_id)
    return ApprovalRead(
        id=approval.id,
        org_id=approval.org_id,
        agent_id=approval.agent_id,
        agent_name=agent.name if agent else approval.agent_id,
        transaction_id=approval.transaction_id,
        chain_id=tx.chain_id if tx else "",
        from_address=tx.from_address if tx else "",
        to_address=tx.to_address if tx else None,
        value_wei=tx.value_wei if tx else 0,
        decision=approval.decision,
        status=approval.status,
        reasons=approval.reasons or [],
        risk_summary=approval.risk_summary,
        confidence=approval.confidence,
        expires_at=approval.expires_at,
        decided_by=approval.decided_by,
        decided_at=approval.decided_at,
        decision_note=approval.decision_note,
        created_at=approval.created_at,
    )


@router.get("", response_model=list[ApprovalRead])
def list_approvals(
    status_filter: str = "pending",
    agent_id: str | None = None,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_reviewer),
) -> list[ApprovalRead]:
    if status_filter not in {"pending", "approved", "rejected", "expired"}:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid status filter")
    _expire_overdue(db, user.org_id)
    stmt = select(Approval).where(Approval.org_id == user.org_id, Approval.status == status_filter)
    if agent_id:
        stmt = stmt.where(Approval.agent_id == agent_id)
    rows = db.scalars(stmt.order_by(Approval.created_at.desc()).limit(200)).all()
    return [_to_read(db, a) for a in rows]


def _decide(
    approval_id: str,
    body: ApprovalDecisionBody,
    outcome: str,
    db: Session,
    user: CurrentUser,
) -> ApprovalRead:
    approval = _get_pending(db, approval_id, user.org_id)
    if approval.status != "pending":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Approval already decided: {approval.status}",
        )
    now = datetime.now(UTC)
    approval.status = outcome
    approval.decided_by = user.id
    approval.decided_at = now
    approval.decision_note = body.note

    tx = db.get(Transaction, approval.transaction_id)
    if tx is not None and tx.org_id == user.org_id:
        tx.status = outcome
    db.commit()
    db.refresh(approval)
    return _to_read(db, approval)


@router.post("/{approval_id}/approve", response_model=ApprovalRead)
def approve(
    approval_id: str,
    body: ApprovalDecisionBody,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_reviewer),
) -> ApprovalRead:
    return _decide(approval_id, body, "approved", db, user)


@router.post("/{approval_id}/reject", response_model=ApprovalRead)
def reject(
    approval_id: str,
    body: ApprovalDecisionBody,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_reviewer),
) -> ApprovalRead:
    return _decide(approval_id, body, "rejected", db, user)
