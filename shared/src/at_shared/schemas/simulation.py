"""Simulation contract (FR-MCP-01 / FR-CHAIN-01) — shared by mcp-server and
the blockchain service.

This schema is FROZEN: it is the cross-chain contract and is contract-tested.
Simulator backends may only vary the `simulator` field; the result structure
is identical for every supported chain.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from at_shared.schemas.tx import ChainId
from pydantic import BaseModel, Field, field_validator


class SimulateRequest(BaseModel):
    """Input for a simulation — identical shape on every chain."""

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
    """A single storage-slot / balance change captured by the simulation."""

    address: str
    slot: str = Field(description="storage key as 0x-prefixed hex; 'balance' for native balance")
    before: str = Field(description="pre-state value as 0x-prefixed hex")
    after: str = Field(description="post-state value as 0x-prefixed hex")


class SimulationStatus(StrEnum):
    SUCCESS = "success"
    REVERTED = "reverted"
    ERROR = "error"


class SimulationResult(BaseModel):
    """Structured simulation result — the cross-chain contract (FR-MCP-01)."""

    chain_id: ChainId
    status: Literal["success", "reverted", "error"]
    gas_used_wei: int = Field(ge=0)
    gas_ceiling_used: bool = Field(
        description="true when the estimate hit the policy gas ceiling"
    )
    state_diff: list[StateDiffEntry] = Field(default_factory=list)
    revert_reason: str | None = None
    simulated_at: datetime
    simulator: Literal["stub", "anvil-fork", "anvil-local", "tenderly"] = "stub"