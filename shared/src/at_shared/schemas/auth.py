"""Auth / token / API-key schemas."""

from __future__ import annotations

from datetime import datetime

from at_shared.schemas.common import OrmModel, Role
from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    must_change_password: bool = False


class RefreshRequest(BaseModel):
    refresh_token: str


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=8, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)


class CurrentUser(OrmModel):
    id: str
    org_id: str
    email: EmailStr
    role: Role
    is_active: bool


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    agent_ids: list[str] = Field(default_factory=list, max_length=50)


class ApiKeyCreated(BaseModel):
    id: str
    name: str
    agent_ids: list[str]
    created_at: datetime
    # shown exactly once at creation; cannot be retrieved again
    api_key: str


class ApiKeyRead(OrmModel):
    id: str
    name: str
    agent_ids: list[str]
    created_at: datetime
    last_used_at: datetime | None = None