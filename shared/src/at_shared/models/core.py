"""Core relational entities for AgentThreshold (TRD Section 7.1).

Phase 1 covers: Organization, User, Agent, Policy.
Transaction/Simulation/Anomaly/Approval/Audit come in Phase 2.
Audit records use ON DELETE RESTRICT — never cascade-deleted.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from at_shared.db import Base
from at_shared.uuid7 import uuid7

# --- Common column type aliases --------------------------------------------
UuidPk = Annotated[
    str,
    mapped_column(String(36), primary_key=True, default=uuid7),
]
CreatedAt = Annotated[
    datetime,
    mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False),
]
UpdatedAt = Annotated[
    datetime,
    mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    ),
]


def utcnow() -> datetime:
    return datetime.now(UTC)


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[UuidPk]
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    tier: Mapped[str] = mapped_column(String(40), nullable=False, server_default="standard")
    created_at: Mapped[CreatedAt]

    agents: Mapped[list[Agent]] = relationship(back_populates="organization")
    users: Mapped[list[User]] = relationship(back_populates="organization")


class User(Base):
    __tablename__ = "users"

    id: Mapped[UuidPk]
    org_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    role: Mapped[str] = mapped_column(String(40), nullable=False)  # admin|approver|auditor|developer
    password_hash: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    must_change_password: Mapped[bool] = mapped_column(default=False, nullable=False)
    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]

    organization: Mapped[Organization] = relationship(back_populates="users")


class Agent(Base):
    __tablename__ = "agents"
    __table_args__ = (
        Index("ix_agents_org_id", "org_id"),
        Index("ix_agents_org_wallet", "org_id", "wallet_address", unique=True),
    )

    id: Mapped[UuidPk]
    org_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    wallet_address: Mapped[str] = mapped_column(String(42), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="active")
    # kill-switch: when set, 100% of screening requests for this agent are rejected
    halted: Mapped[bool] = mapped_column(default=False, nullable=False)
    halt_reason: Mapped[str | None] = mapped_column(String(500))
    halted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]

    organization: Mapped[Organization] = relationship(back_populates="agents")
    policies: Mapped[list[Policy]] = relationship(back_populates="agent")


class ApiKey(Base):
    __tablename__ = "api_keys"
    __table_args__ = (Index("ix_api_keys_org_id", "org_id"),)

    id: Mapped[UuidPk]
    org_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    # sha256 hash of the raw key; raw key shown once at creation
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    key_prefix: Mapped[str] = mapped_column(String(12), nullable=False)
    # agent IDs this key is scoped to; empty = org-wide service key
    agent_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[CreatedAt]

    organization: Mapped[Organization] = relationship()


class Policy(Base):
    __tablename__ = "policies"
    __table_args__ = (
        Index("ix_policies_agent_version", "agent_id", "version"),
    )

    id: Mapped[UuidPk]
    agent_id: Mapped[str] = mapped_column(
        ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False
    )
    version: Mapped[int] = mapped_column(nullable=False)
    # spend_limit_usd: max value (USD-normalized) per transaction; null = unlimited
    spend_limit_usd: Mapped[float | None] = mapped_column()
    # daily_spend_limit_usd: rolling 24h ceiling; null = unlimited
    daily_spend_limit_usd: Mapped[float | None] = mapped_column()
    # allow_list: permitted counterparties (addresses); empty = no restriction
    allow_list: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    # deny_list: always-blocked counterparties; evaluated before allow_list
    deny_list: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    # rate_limit: max requests per rolling window (seconds)
    rate_limit_per_minute: Mapped[int | None] = mapped_column()
    # time-of-day window (UTC, minutes since midnight)
    active_from_minute: Mapped[int | None] = mapped_column()
    active_to_minute: Mapped[int | None] = mapped_column()
    # gas ceiling in wei
    gas_ceiling: Mapped[int | None] = mapped_column(BigInteger())
    # anomaly escalation threshold (0-100)
    anomaly_threshold: Mapped[float] = mapped_column(default=70.0, nullable=False)
    created_by: Mapped[str] = mapped_column(String(36), nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    created_at: Mapped[CreatedAt]

    agent: Mapped[Agent] = relationship(back_populates="policies")