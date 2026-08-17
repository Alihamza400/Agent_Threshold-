"""Append-only audit records and their on-chain anchor batches (FR-AUDIT-01).

Every screening decision is written as an immutable `AuditRecord` whose
`event_hash` is the keccak256 Merkle leaf. The audit-service batcher folds
unbatched records into a Merkle tree every 15 min / 1,000 records and submits
the root to AuditAnchor.sol, then marks `anchored_batch_id` on the records and
records the batch in `anchor_batches` — giving every record a recoverable
on-chain Merkle proof path.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from at_shared.db import Base
from at_shared.uuid7 import uuid7

UuidPk = Annotated[str, mapped_column(String(36), primary_key=True, default=uuid7)]


class AuditRecord(Base):
    __tablename__ = "audit_records"
    __table_args__ = (
        Index("ix_audit_org_created", "org_id", "created_at"),
        Index("ix_audit_anchored", "anchored_batch_id"),
        Index("ix_audit_event_hash", "event_hash"),
    )

    id: Mapped[UuidPk]
    org_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    agent_id: Mapped[str] = mapped_column(
        ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False
    )
    transaction_id: Mapped[str | None] = mapped_column(
        ForeignKey("transactions.id", ondelete="RESTRICT")
    )
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)  # decision
    # keccak256 leaf (64 hex chars); the record's position in the audit tree.
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # Enough to rebuild the canonical record without joining volatile tables.
    details: Mapped[dict] = mapped_column(JSON, nullable=False)
    # Set once the record is included in an anchored batch (else NULL).
    anchored_batch_id: Mapped[int | None] = mapped_column()

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    agent = relationship("Agent")


class AnchorBatch(Base):
    __tablename__ = "anchor_batches"
    __table_args__ = (Index("ix_anchor_batch_id", "batch_id", unique=True),)

    id: Mapped[UuidPk]
    # On-chain batch id (strictly increasing per AuditAnchor).
    batch_id: Mapped[int] = mapped_column(BigInteger(), nullable=False, unique=True)
    merkle_root: Mapped[str] = mapped_column(String(64), nullable=False)
    record_count: Mapped[int] = mapped_column(default=0, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="submitted"
    )  # submitted|anchored|failed
    tx_hash: Mapped[str | None] = mapped_column(String(66))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    anchored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )