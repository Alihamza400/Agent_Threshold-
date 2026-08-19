"""Typed errors for the AgentThreshold SDK.

Fail-closed by construction (SR-04): every error raised by the SDK means the
transaction MUST NOT be signed or broadcast. There is deliberately no
"best-effort" path — a screening that cannot be verified raises a
`ScreeningUnavailableError`, never a silent approval.
"""

from __future__ import annotations

from .schemas import Decision

__all__ = [
    "AgentThresholdError",
    "ScreeningError",
    "ScreeningEscalatedError",
    "ScreeningRejectedError",
    "ScreeningUnavailableError",
    "TransportError",
    "UnauthorizedError",
]


class AgentThresholdError(Exception):
    """Base class for all SDK errors."""


class TransportError(AgentThresholdError):
    """Network failure, timeout, or malformed response from the gateway.

    The screening outcome is unknown -> the transaction must fail closed.
    """


class UnauthorizedError(AgentThresholdError):
    """The API key was rejected (401). Check key value and agent scope."""


class ScreeningError(AgentThresholdError):
    """A screening outcome that forbids signing."""

    def __init__(self, message: str, *, decision: Decision | None = None) -> None:
        self.decision = decision
        super().__init__(message)


class ScreeningRejectedError(ScreeningError):
    """The pipeline rejected the transaction; it must not be signed."""

    def __init__(self, decision: Decision) -> None:
        super().__init__(_describe(decision), decision=decision)


class ScreeningEscalatedError(ScreeningError):
    """The transaction was escalated for human review; do not sign."""

    def __init__(self, decision: Decision) -> None:
        super().__init__(_describe(decision), decision=decision)


class ScreeningUnavailableError(ScreeningError):
    """Screening could not complete (HTTP 5xx / timeout / malformed body).

    Fail-closed: the outcome is unknown, so the transaction must not be
    signed or broadcast.
    """


def _describe(decision: Decision) -> str:
    reasons = "; ".join(decision.reasons) if decision.reasons else "no reasons"
    return (
        f"transaction {decision.decision.value} by AgentThreshold "
        f"(confidence={decision.confidence:.1f}, transaction_id={decision.transaction_id}): {reasons}"
    )
