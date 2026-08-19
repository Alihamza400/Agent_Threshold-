"""Rolling behavioral baseline per agent (TRD FR-DATA-02, FR-AI-02).

Aggregated 90-day statistics used by the Anomaly Scorer. Updated within
minutes of a confirmed transaction. `features` holds the statistical vector;
a pgvector embedding column is a post-MVP upgrade.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from at_shared.db import Base
from at_shared.uuid7 import uuid7

UuidPk = Annotated[str, mapped_column(String(36), primary_key=True, default=uuid7)]
WeiInt = Annotated[int, mapped_column()]


class BaselineProfile(Base):
    __tablename__ = "baseline_profiles"
    __table_args__ = (Index("ix_baseline_agent", "agent_id"),)

    id: Mapped[UuidPk]
    agent_id: Mapped[str] = mapped_column(
        ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False
    )
    window_days: Mapped[int] = mapped_column(default=90, nullable=False)

    # statistical summary of the rolling window
    tx_count: Mapped[int] = mapped_column(default=0, nullable=False)
    # wei volumes can exceed the 32-bit INTEGER range -> BigInteger (matches
    # migration 0004; keeps create_all consistent with the production schema).
    total_volume_wei: Mapped[int] = mapped_column(BigInteger(), default=0, nullable=False)
    mean_value_wei: Mapped[float] = mapped_column(default=0.0, nullable=False)
    median_value_wei: Mapped[float] = mapped_column(default=0.0, nullable=False)
    std_value_wei: Mapped[float] = mapped_column(default=0.0, nullable=False)
    avg_freq_per_day: Mapped[float] = mapped_column(default=0.0, nullable=False)
    unique_counterparties: Mapped[int] = mapped_column(default=0, nullable=False)

    # full feature vector for the scorer (JSON), for reproducibility
    features: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )