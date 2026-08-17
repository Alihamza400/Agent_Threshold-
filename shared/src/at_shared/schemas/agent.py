"""Organization and Agent schemas."""

from __future__ import annotations

from datetime import datetime

from at_shared.schemas.common import AgentStatus, OrmModel
from pydantic import BaseModel, Field


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    tier: str = Field(default="standard", pattern=r"^(standard|pro|enterprise)$")


class OrganizationRead(OrmModel):
    id: str
    name: str
    tier: str
    created_at: datetime


class AgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    wallet_address: str = Field(min_length=42, max_length=42)


class AgentRead(OrmModel):
    id: str
    org_id: str
    name: str
    wallet_address: str
    status: AgentStatus
    halted: bool
    halt_reason: str | None = None
    created_at: datetime


class AgentRegistered(BaseModel):
    agent: AgentRead
    default_policy_id: str | None = None