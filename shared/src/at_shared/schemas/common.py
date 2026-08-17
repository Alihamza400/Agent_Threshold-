"""Common Pydantic schemas shared across AgentThreshold services."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Role(StrEnum):
    """RBAC roles (TRD FR-AUTH-02)."""

    ADMIN = "admin"
    APPROVER = "approver"
    AUDITOR = "auditor"
    DEVELOPER = "developer"


class OrmModel(BaseModel):
    """Base schema with ORM attribute-read enabled."""

    model_config = ConfigDict(from_attributes=True)


class AgentStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    HALTED = "halted"


class ErrorResponse(BaseModel):
    detail: str
    code: str | None = Field(default=None)


class Paginated(BaseModel):
    items: list
    next_cursor: str | None = None
    total: int | None = None