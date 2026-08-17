"""Structured output schemas for the LLM screening agents (TRD 4.5).

Every LLM response is validated against these strict schemas before use;
malformed output is treated as a failure (fail-closed, TRD 4.10).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


class ActionClass(StrEnum):
    SWAP = "swap"
    TRANSFER = "transfer"
    APPROVAL = "approval"
    CONTRACT_INTERACTION = "contract_interaction"
    GAS_FEE = "gas_fee"
    WITHDRAW = "withdraw"
    OTHER = "other"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RecommendedAction(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    INVESTIGATE = "investigate"


class IntentClassification(BaseModel):
    """Output of the Intent Classifier (advisory only, FR-AI-01)."""

    action_class: ActionClass
    expected_scope: str = Field(min_length=1, max_length=500)
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("action_class")
    @classmethod
    def _must_be_action_class(cls, v):
        return v


class RiskSummary(BaseModel):
    """Output of the Simulation Interpreter (FR-AI-03)."""

    summary: str = Field(min_length=1, max_length=1000)
    risk_level: RiskLevel
    risk_tags: list[str] = Field(default_factory=list, max_length=10)
    balance_drain: bool = False
    total_impact_usd: float | None = Field(default=None, ge=0.0)


class EscalationDraft(BaseModel):
    """Output of the Escalation Drafting Agent (human approval request)."""

    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=1000)
    recommended_action: RecommendedAction
    key_risks: list[str] = Field(default_factory=list, max_length=8)
    questions_for_approver: list[str] = Field(default_factory=list, max_length=5)


class StructuredAgentOutput(BaseModel):
    """Wrapper the pipeline records for every LLM stage (prompt version etc.)."""

    prompt_version: str
    model: str
    latency_ms: int
    result: IntentClassification | RiskSummary | EscalationDraft