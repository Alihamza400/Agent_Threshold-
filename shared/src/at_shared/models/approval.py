"""Escalation / approval records (Phase 7.3, TRD Section 7.1).

An escalation is created when screening returns `decision=escalate` and a human
approver must act before the transaction may be executed. State machine:

    pending --approve--> approved
    pending --reject-->  rejected
    pending --expire-->  expired        (unresolved => default reject)

Transitions are idempotency-guarded at the API layer (409 on double-decision)
and by the fact that `transaction_id` is unique (one escalation per decision).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from at_shared.db import Base
from at_shared.uuid7 import uuid7

UuidPk = Annotated[str, mapped_column(String(36), primary_key=True, default=uuid7)]


class Approval(Base):
    __tablename__ = "approvals"
    __table_args__ = (
        Index("ix_approvals_org_status", "org_id", "status"),
        Index("ix_approvals_status_created", "status", "created_at"),
    )

    id: Mapped[UuidPk]
    org_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    agent_id: Mapped[str] = mapped_column(
        ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False
    )
    # One escalation per decision; uniqueness prevents double-decision races.
    transaction_id: Mapped[str] = mapped_column(
        ForeignKey("transactions.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    # Original screening decision that triggered the escalation (always "escalate").
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="pending"
    )  # pending|approved|rejected|expired
    reasons: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    risk_summary: Mapped[str | None] = mapped_column()
    confidence: Mapped[float] = mapped_column(default=0.0, nullable=False)
    # Unresolved escalations expire and default to reject (fail-closed).
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    decided_by: Mapped[str | None] = mapped_column(String(36))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(String(500))

    # Notification delivery state (task 8.4). Owned by the escalation
    # notification worker; the human decision queue never reads these. A
    # notification failure must NEVER affect the approval outcome.
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notify_attempts: Mapped[int] = mapped_column(default=0, nullable=False)
    notify_last_error: Mapped[str | None] = mapped_column(String(500))
    notify_next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    transaction = relationship("Transaction")