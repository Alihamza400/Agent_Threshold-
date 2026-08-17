"""MCP tool schemas + response-schema validation (task 4.4).

The simulation schema is the cross-chain contract (FR-MCP-01) and lives in
at-shared so the blockchain service and MCP server share one frozen shape.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from at_shared.schemas.simulation import SimulateRequest, SimulationResult  # noqa: F401
from pydantic import BaseModel

from mcp_server.errors import MCPSchemaError


class PolicyRead(BaseModel):
    """Active policy snapshot (read-only, FR-MCP-02)."""

    agent_id: str
    version: int
    spend_limit_usd: float | None
    daily_spend_limit_usd: float | None
    allow_list: list[str]
    deny_list: list[str]
    rate_limit_per_minute: int | None
    gas_ceiling: int | None
    anomaly_threshold: float
    active_from_minute: int | None
    active_to_minute: int | None
    is_active: bool


class HistoryEntry(BaseModel):
    """One audited transaction record (read-only, FR-MCP-02)."""

    id: str
    chain_id: str | None
    to_address: str | None
    value_wei: int
    decision: str
    risk_summary: str
    created_at: datetime


class HistoryResult(BaseModel):
    agent_id: str
    entries: list[HistoryEntry]


def validate_result[T: BaseModel](schema: type[T], data: Any) -> T:
    """Validate a tool result against its declared schema (task 4.4).

    Malformed output is a failure, never silently passed through.
    """
    try:
        return schema.model_validate(data)
    except Exception as exc:  # noqa: BLE001 - convert to structured failure
        raise MCPSchemaError(f"tool result failed validation: {exc}") from exc


def utcnow() -> datetime:
    return datetime.now(UTC)