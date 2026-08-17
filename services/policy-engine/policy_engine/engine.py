"""Deterministic policy evaluation engine.

Pure functions only — no I/O, no network, no LLM. The same inputs always
produce the same decision (TRD FR-AI-02 determinism, SR-02).

Fail-closed semantics:
  - An error evaluating a rule must never result in auto-approval.
  - Violations collect reasons; the harshest applicable decision wins.
  - Anomaly/confidence input is advisory and can only escalate, never approve.

Rule precedence (highest first):
  deny_list -> allow_list -> spend limit -> daily spend -> rate limit
  -> time window -> gas ceiling -> anomaly escalation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from at_shared.schemas.tx import DecisionType


@dataclass(frozen=True)
class PolicyData:
    """Immutable snapshot of an agent's active policy for evaluation."""

    version: int
    spend_limit_usd: float | None = None
    daily_spend_limit_usd: float | None = None
    allow_list: tuple[str, ...] = ()
    deny_list: tuple[str, ...] = ()
    rate_limit_per_minute: int | None = None
    active_from_minute: int | None = None
    active_to_minute: int | None = None
    gas_ceiling: int | None = None
    anomaly_threshold: float = 70.0

    @classmethod
    def from_orm(cls, policy) -> PolicyData:
        return cls(
            version=policy.version,
            spend_limit_usd=policy.spend_limit_usd,
            daily_spend_limit_usd=policy.daily_spend_limit_usd,
            allow_list=tuple(policy.allow_list or []),
            deny_list=tuple(policy.deny_list or []),
            rate_limit_per_minute=policy.rate_limit_per_minute,
            active_from_minute=policy.active_from_minute,
            active_to_minute=policy.active_to_minute,
            gas_ceiling=policy.gas_ceiling,
            anomaly_threshold=policy.anomaly_threshold,
        )


@dataclass(frozen=True)
class EngineContext:
    """Request-scoped runtime inputs the engine reads but cannot mutate."""

    usd_value: float | None = None          # price-oracle normalized value
    daily_spend_used_usd: float = 0.0       # rolling 24h spend already used
    recent_tx_count: int = 0                # tx in the current rate window
    known_counterparties: frozenset[str] = frozenset()  # addresses seen in the last 90 days
    anomaly_score: float | None = None      # 0-100 advisory score from Anomaly Scorer
    now_utc_minute: int | None = None       # minutes since midnight UTC; default = real now
    fail_closed: bool = True                # True unless explicitly disabled by config

    @classmethod
    def default_now(cls) -> EngineContext:
        now = datetime.now(UTC)
        return cls(now_utc_minute=now.hour * 60 + now.minute)


@dataclass
class EngineResult:
    decision: DecisionType
    reasons: list[str] = field(default_factory=list)
    policy_version: int | None = None

    def merge(self, other: EngineResult) -> EngineResult:
        """Combine results; the harshest decision wins (reject > escalate > approve)."""
        rank = {DecisionType.REJECT: 2, DecisionType.ESCALATE: 1, DecisionType.APPROVE: 0}
        self.reasons.extend(other.reasons)
        if rank[other.decision] > rank[self.decision]:
            self.decision = other.decision
        return self


def _reject(reason: str) -> EngineResult:
    return EngineResult(decision=DecisionType.REJECT, reasons=[reason])


def _escalate(reason: str) -> EngineResult:
    return EngineResult(decision=DecisionType.ESCALATE, reasons=[reason])


def _approve() -> EngineResult:
    return EngineResult(decision=DecisionType.APPROVE)


def evaluate(policy: PolicyData, to_address: str | None, value_wei: int, gas_ceiling_used: int | None, ctx: EngineContext) -> EngineResult:
    """Evaluate a canonical transaction against a policy. Deterministic.

    Args:
        to_address: counterparty (None for contract deployment).
        value_wei: native value in wei.
        gas_ceiling_used: requested gas limit for the tx.
        ctx: EngineContext runtime inputs.
    """
    result = EngineResult(decision=DecisionType.APPROVE, policy_version=policy.version)

    # ---- Fail-closed guard: engine internal error must not approve ---------
    if ctx.fail_closed is False:
        result = result.merge(EngineResult(decision=DecisionType.ESCALATE, reasons=["fail-open mode disabled by operator"]))
    # NOTE: engine itself is pure; a real internal failure surfaces as an
    # exception in the caller, which the orchestrator maps to reject/escalate.

    to = to_address.lower() if to_address else None

    # 1. Deny list — always reject regardless of anything else.
    if to in {a.lower() for a in policy.deny_list}:
        return result.merge(_reject("counterparty is on the deny list"))

    # 2. Allow list — non-empty allow list restricts counterparties.
    if policy.allow_list:
        allowed = {a.lower() for a in policy.allow_list}
        if to is not None and to not in allowed:
            return result.merge(_reject("counterparty is not on the allow list"))

    # 3. Per-transaction spend limit (USD-normalized).
    usd = ctx.usd_value
    if policy.spend_limit_usd is not None and usd is not None and usd > policy.spend_limit_usd:
        return result.merge(_reject(f"value ${usd:,.2f} exceeds per-tx spend limit ${policy.spend_limit_usd:,.2f}"))

    # 4. Rolling daily spend limit.
    if (
        policy.daily_spend_limit_usd is not None
        and usd is not None
        and (ctx.daily_spend_used_usd + usd) > policy.daily_spend_limit_usd
    ):
        return result.merge(
            _reject(
                f"would exceed daily spend limit "
                f"${policy.daily_spend_limit_usd:,.2f} (used ${ctx.daily_spend_used_usd:,.2f})"
            )
        )

    # 5. Rate limit (tx count in rolling window).
    if (
        policy.rate_limit_per_minute is not None
        and ctx.recent_tx_count >= policy.rate_limit_per_minute
    ):
        return result.merge(_reject(f"rate limit {policy.rate_limit_per_minute}/min reached"))

    # 6. Time-of-day window (UTC minutes since midnight).
    if (
        policy.active_from_minute is not None
        and policy.active_to_minute is not None
        and ctx.now_utc_minute is not None
        and not (policy.active_from_minute <= ctx.now_utc_minute < policy.active_to_minute)
    ):
        return result.merge(_reject("outside configured active time window"))

    # 7. Gas ceiling (gas-griefing / fee-drain protection, FR-CHAIN-02).
    if (
        policy.gas_ceiling is not None
        and gas_ceiling_used is not None
        and gas_ceiling_used > policy.gas_ceiling
    ):
        return result.merge(_reject(f"gas {gas_ceiling_used} exceeds ceiling {policy.gas_ceiling}"))

    # 8. Anomaly — advisory only: can escalate, never approve.
    if ctx.anomaly_score is not None and ctx.anomaly_score >= policy.anomaly_threshold:
        return result.merge(
            _escalate(f"anomaly score {ctx.anomaly_score:.0f} >= threshold {policy.anomaly_threshold:.0f}")
        )

    # 9. New counterparty with real value — conservative escalation.
    if value_wei > 0 and to is not None and to not in ctx.known_counterparties:
        return result.merge(_escalate("first transaction to previously unseen counterparty"))

    return result