"""Pydantic schemas for every MCP tool + response-schema validation (4.4).

The simulation schema is the cross-chain contract (FR-MCP-01): identical
structure for every supported chain so contract tests can assert consistency.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal, TypeVar

from at_shared.schemas.tx import ChainId
from pydantic import BaseModel, Field, field_validator

from mcp_server.errors import MCPSchemaError

T = TypeVar("T", bound=BaseModel)


class SimulateRequest(BaseModel):
    """Input for the `simulate_transaction` tool (FR-MCP-01)."""

    agent_id: str
    chain_id: ChainId
    from_address: str
    to_address: str | None = None
    value_wei: int = Field(ge=0)
    calldata: str | None = None

    @field_validator("from_address", "to_address")
    @classmethod
    def _addr(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if not v.startswith("0x") or len(v) != 42:
            raise ValueError("must be a 0x-prefixed 40-hex-char address")
        return v.lower()


class StateDiffEntry(BaseModel):
    """A single storage slot change captured by the fork simulation."""

    address: str
    slot: str = Field(description="storage key as 0x-prefixed hex")
    before: str = Field(description="pre-state value as 0x-prefixed hex")
    after: str = Field(description="post-state value as 0x-prefixed hex")


class SimulationResult(BaseModel):
    """Structured simulation result — the cross-chain contract (FR-MCP-01).

    Identical schema for every chain_id; simulator backends may only vary
    the `simulator` field. Phase 5 swaps the stub backend for an isolated
    Anvil fork; this schema is frozen now.
    """

    chain_id: ChainId
    status: Literal["success", "reverted", "error"]
    gas_used_wei: int = Field(ge=0)
    gas_ceiling_used: bool = Field(
        description="true when the estimate hit the policy gas ceiling"
    )
    state_diff: list[StateDiffEntry] = Field(default_factory=list)
    revert_reason: str | None = None
    simulated_at: datetime
    simulator: Literal["stub", "anvil-fork"] = "stub"


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