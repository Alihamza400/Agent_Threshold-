"""Orchestrator-specific errors.

All pipeline errors derive from OrchestratorError so callers can fail
closed uniformly. A stage that exceeds its budget raises StageBudgetError
(a timeout); any other stage failure raises StageError. Both are surfaced
through the soft stage runner, which maps them to a reject/escalate decision
per the stage's fail-closed semantics (SR-04).
"""

from __future__ import annotations


class OrchestratorError(Exception):
    """Base error for the orchestrator pipeline."""


class StageBudgetError(OrchestratorError):
    """A pipeline stage exceeded its wall-clock budget (per-stage timeout)."""

    def __init__(self, stage: str, budget_seconds: float) -> None:
        self.stage = stage
        self.budget_seconds = budget_seconds
        super().__init__(f"stage '{stage}' exceeded budget {budget_seconds:.2f}s")


class StageError(OrchestratorError):
    """A pipeline stage raised an unexpected error."""

    def __init__(self, stage: str, cause: BaseException | None = None) -> None:
        self.stage = stage
        self.cause = cause
        super().__init__(f"stage '{stage}' failed: {cause}")
