"""Canonical transaction model and decision records (TRD 2.2.7, Section 7.1)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from at_shared.db import Base
from at_shared.uuid7 import uuid7

UuidPk = Annotated[str, mapped_column(String(36), primary_key=True, default=uuid7)]
WeiInt = Annotated[int, mapped_column(BigInteger())]


class Transaction(Base):
    """Canonical, chain-normalized transaction record.

    ON DELETE RESTRICT: audit/decision history is never cascade-deleted.

    Status lifecycle (task 8.5 execution adapter):
        screened      -> initial record written by the screening pipeline
        approved      -> policy/human Approve decision (execution eligible)
        broadcasting  -> submit started, pre-broadcast (transient)
        broadcast     -> eth_sendRawTransaction accepted; awaiting confirmation
        executed      -> confirmed to chain depth
        stuck         -> broadcast but unconfirmed beyond the timeout
        reorged       -> confirmed block was orphaned (reorg flag)
        rejected      -> policy/human Reject, or unresolved escalation expiry
        cancelled     -> explicit cancel; RBF/cancel replacement broadcast
    """

    __tablename__ = "transactions"
    __table_args__ = (
        Index("ix_transactions_agent_created", "agent_id", "created_at"),
        Index("ix_transactions_exec_status", "status", "broadcast_at"),
    )

    id: Mapped[UuidPk]
    agent_id: Mapped[str] = mapped_column(
        ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False
    )
    org_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    chain_id: Mapped[str] = mapped_column(String(40), nullable=False)
    # canonical fields (FR-DATA-01 normalization)
    from_address: Mapped[str] = mapped_column(String(42), nullable=False)
    to_address: Mapped[str | None] = mapped_column(String(42))
    value_wei: Mapped[WeiInt]
    usd_value: Mapped[float | None] = mapped_column()
    token: Mapped[str | None] = mapped_column(String(42))
    calldata: Mapped[str | None] = mapped_column()
    gas_limit: Mapped[int | None] = mapped_column(BigInteger())
    gas_price_wei: Mapped[int | None] = mapped_column(BigInteger())
    raw_params: Mapped[dict] = mapped_column(JSON, nullable=False)

    decision: Mapped[str] = mapped_column(String(20), nullable=False)  # approve|reject|escalate
    confidence: Mapped[float] = mapped_column(default=0.0, nullable=False)
    risk_summary: Mapped[str | None] = mapped_column()
    reasons: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    policy_version: Mapped[int | None] = mapped_column()
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="screened")
    trace_id: Mapped[str | None] = mapped_column(String(64))
    # wall-clock time spent in the screening pipeline (ms) — drives latency SLOs.
    screened_ms: Mapped[int | None] = mapped_column()

    # Execution adapter lifecycle (task 8.5).
    tx_hash: Mapped[str | None] = mapped_column(String(66))
    nonce: Mapped[int | None] = mapped_column(BigInteger())
    broadcast_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    broadcast_attempts: Mapped[int] = mapped_column(default=0, nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    block_number: Mapped[int | None] = mapped_column(BigInteger())
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stuck_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reorged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    agent = relationship("Agent")