"""Canonical transaction + decision schemas (TRD FR-DATA-01, FR-API-01)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from at_shared.schemas.common import OrmModel
from pydantic import BaseModel, Field, field_validator


class ChainId(StrEnum):
    ETHEREUM = "ethereum"
    BASE = "base"
    ARBITRUM = "arbitrum"


class DecisionType(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    ESCALATE = "escalate"


class TxStatus(StrEnum):
    SCREENED = "screened"
    APPROVED = "approved"
    REJECTED = "rejected"
    ESCALATED = "escalated"
    CONFIRMED = "confirmed"


def _validate_address(v: str) -> str:
    if not v.startswith("0x") or len(v) != 42:
        raise ValueError("must be a 0x-prefixed 40-hex-char address")
    return v.lower()


class ScreenRequest(BaseModel):
    """POST /v1/transactions/screen payload."""

    agent_id: str
    chain_id: ChainId
    from_address: str = Field(description="agent wallet")
    to_address: str | None = Field(default=None, description="counterparty; null for contract deploy")
    value_wei: int = Field(ge=0)
    calldata: str | None = Field(default=None)
    gas_limit: int | None = Field(default=None, ge=0)
    gas_price_wei: int | None = Field(default=None, ge=0)
    token: str | None = Field(default=None, description="ERC20 address if token transfer")
    task_context: str | None = Field(
        default=None, max_length=2000, description="untrusted agent task context (advisory only)"
    )

    @field_validator("from_address", "to_address", "token")
    @classmethod
    def _addr(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return _validate_address(v)


class Decision(BaseModel):
    """Decision object returned by the screening pipeline (TRD FR-API-01)."""

    decision: DecisionType
    reasons: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=100.0)
    risk_summary: str | None = None
    policy_version: int | None = None
    transaction_id: str | None = None


class TransactionRead(OrmModel):
    id: str
    agent_id: str
    org_id: str
    chain_id: str
    from_address: str
    to_address: str | None
    value_wei: int
    usd_value: float | None
    token: str | None
    decision: str
    confidence: float
    risk_summary: str | None
    reasons: list[str]
    policy_version: int | None
    status: str
    screened_ms: int | None = None
    created_at: datetime