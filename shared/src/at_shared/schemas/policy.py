"""Policy configuration schemas (Phase 7.2 — versioned, audit-friendly)."""

from __future__ import annotations

from datetime import datetime

from at_shared.schemas.common import OrmModel
from pydantic import BaseModel, Field, model_validator


class PolicyUpdate(BaseModel):
    """Partial update; omitted fields carry over from the active policy.

    A PUT always creates a NEW immutable version (append-only history) and
    deactivates the previous one — the screening engine reads the newest
    active row, so enforcement is atomic with publication.
    """

    spend_limit_usd: float | None = Field(default=None, ge=0)
    daily_spend_limit_usd: float | None = Field(default=None, ge=0)
    allow_list: list[str] | None = None
    deny_list: list[str] | None = None
    rate_limit_per_minute: int | None = Field(default=None, ge=0, le=100_000)
    active_from_minute: int | None = Field(default=None, ge=0, le=1439)
    active_to_minute: int | None = Field(default=None, ge=0, le=1439)
    gas_ceiling: int | None = Field(default=None, ge=0)
    anomaly_threshold: float = Field(default=70.0, ge=0, le=100)
    # Optional note stored on the new version for the change audit trail.
    change_note: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _window_ordered(self) -> PolicyUpdate:
        if (
            self.active_from_minute is not None
            and self.active_to_minute is not None
            and self.active_to_minute < self.active_from_minute
        ):
            raise ValueError("active_to_minute must be >= active_from_minute")
        return self


class PolicyRead(OrmModel):
    agent_id: str
    version: int
    spend_limit_usd: float | None = None
    daily_spend_limit_usd: float | None = None
    allow_list: list[str] = []
    deny_list: list[str] = []
    rate_limit_per_minute: int | None = None
    active_from_minute: int | None = None
    active_to_minute: int | None = None
    gas_ceiling: int | None = None
    anomaly_threshold: float = 70.0
    is_active: bool = True
    created_by: str
    created_at: datetime