"""Screening agent error hierarchy.

All LLM-related failures raise a subclass of `ScreeningAgentError` so the
orchestrator can fail closed (block/escalate) on any of them. A schema
validation failure is treated exactly like a timeout or provider outage.
"""

from __future__ import annotations


class ScreeningAgentError(Exception):
    """Base error for all screening agent failures."""


class LLMTimeoutError(ScreeningAgentError):
    """The LLM call exceeded its bounded budget."""


class LLMProviderError(ScreeningAgentError):
    """Provider returned an error (HTTP 5xx, rate limit, auth)."""


class LLMSchemaError(ScreeningAgentError):
    """Response failed strict schema validation (treated as failure)."""


class CircuitOpenError(ScreeningAgentError):
    """Circuit breaker is tripped; calls refused until cooldown elapses."""