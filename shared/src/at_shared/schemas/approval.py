"""Escalation / approval queue schemas (Phase 7.3)."""

from __future__ import annotations

from datetime import datetime

from at_shared.schemas.common import OrmModel
from pydantic import BaseModel, Field


class ApprovalRead(OrmModel):
    """One escalation, enriched with the transaction context an approver needs."""

    id: str
    org_id: str
    agent_id: str
    agent_name: str
    transaction_id: str
    chain_id: str
    from_address: str
    to_address: str | None = None
    value_wei: int
    decision: str
    status: str  # pending|approved|rejected|expired
    reasons: list[str] = []
    risk_summary: str | None = None
    confidence: float = 0.0
    expires_at: datetime | None = None
    decided_by: str | None = None
    decided_at: datetime | None = None
    decision_note: str | None = None
    created_at: datetime


class ApprovalDecisionBody(BaseModel):
    note: str | None = Field(default=None, max_length=500)