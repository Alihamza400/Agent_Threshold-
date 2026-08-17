"""LLM provider abstraction for screening agents.

- `LLMClient` interface: `complete(system, user, schema) -> T`
- `AnthropicClient`: production provider (Claude, structured output via tool use).
- `MockClient`: deterministic offline fallback used when no ANTHROPIC_API_KEY
  is configured (dev/test) — same interface, schema-valid results.
- Circuit breaker + bounded timeout: any failure -> fail closed at the caller.

All prompts come from the versioned prompt registry (never inline).
"""

from __future__ import annotations

import abc
import os
from typing import TypeVar, cast

from pydantic import BaseModel

from screening_agents.circuit_breaker import CircuitBreaker
from screening_agents.errors import (
    CircuitOpenError,
    LLMProviderError,
    LLMSchemaError,
    LLMTimeoutError,
)

T = TypeVar("T", bound=BaseModel)

DEFAULT_TIMEOUT_MS = 800
DEFAULT_MODEL = "claude-sonnet-4-5"  # low-latency structured-output model


class LLMClient(abc.ABC):
    """Abstract low-latency structured-output client."""

    def __init__(self, *, timeout_ms: int = DEFAULT_TIMEOUT_MS):
        self.timeout_ms = timeout_ms
        self.circuit = CircuitBreaker()
        self.model = DEFAULT_MODEL

    @abc.abstractmethod
    def _complete(self, system: str, user: str, schema: type[T]) -> dict:
        """Raw provider call returning the parsed dictionary."""

    def complete(self, system: str, user: str, schema: type[T]) -> T:
        """Validate output against schema; fail closed on any error."""
        if self.circuit.is_open():
            raise CircuitOpenError("LLM circuit breaker is open")
        try:
            raw = self._complete(system, user, schema)
        except Exception:
            self.circuit.record_failure()
            raise
        try:
            result = schema.model_validate(raw)
        except Exception as exc:  # noqa: BLE001 - schema mismatch -> fail closed
            self.circuit.record_failure()
            raise LLMSchemaError(f"LLM output failed schema validation: {exc}") from exc

        self.circuit.record_success()
        return result


class MockClient(LLMClient):
    """Deterministic fallback used without an API key (dev/test only).

    Produces schema-valid results derived from the user prompt keywords so
    the full pipeline is exercisable offline. NEVER used in production when a
    provider is configured.
    """

    def __init__(self, *, timeout_ms: int = DEFAULT_TIMEOUT_MS):
        super().__init__(timeout_ms=timeout_ms)
        self.model = "mock-deterministic-v1"

    def _complete(self, system: str, user: str, schema: type[T]) -> dict:
        text = user.lower()
        if schema.__name__ == "IntentClassification":
            if "swap" in text:
                action = "swap"
            elif "approv" in text:
                action = "approval"
            elif "withdraw" in text:
                action = "withdraw"
            elif "transfer" in text or "send" in text:
                action = "transfer"
            else:
                action = "contract_interaction"
            return {
                "action_class": action,
                "expected_scope": f"mock scope for {action}",
                "confidence": 0.85,
                "reason": "deterministic mock classification",
            }
        if schema.__name__ == "RiskSummary":
            drain = "drain" in text or "approve unlimited" in text
            return {
                "summary": "mock risk summary (no LLM configured)",
                "risk_level": "critical" if drain else "low",
                "risk_tags": ["balance_drain"] if drain else ["mock"],
                "balance_drain": drain,
            }
        if schema.__name__ == "EscalationDraft":
            return {
                "title": "Human approval required",
                "summary": "mock escalation draft (no LLM configured)",
                "recommended_action": "investigate",
                "key_risks": ["unverified counterparty"],
                "questions_for_approver": ["Has this counterparty been vetted?"],
            }
        raise LLMSchemaError(f"unsupported schema {schema.__name__}")


class AnthropicClient(LLMClient):
    """Production Claude provider (structured output via tool use).

    Requires ANTHROPIC_API_KEY. All calls bounded by timeout_ms; latency
    budget is enforced so the hot path fails closed instead of stalling.
    """

    def __init__(self, *, api_key: str | None = None, timeout_ms: int = DEFAULT_TIMEOUT_MS, model: str = DEFAULT_MODEL):
        super().__init__(timeout_ms=timeout_ms)
        self.model = model
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not self._api_key:
            raise LLMProviderError("ANTHROPIC_API_KEY is required for AnthropicClient")
        try:
            import anthropic  # type: ignore
        except ImportError as exc:  # pragma: no cover - optional dep
            raise LLMProviderError("anthropic SDK not installed (pip install 'at-screening-agents[anthropic]')") from exc
        self._client = anthropic.Anthropic(api_key=self._api_key)

    def _complete(self, system: str, user: str, schema: type[T]) -> dict:
        import anthropic

        timeout_s = self.timeout_ms / 1000.0
        try:
            resp = self._client.messages.create(
                model=self.model,
                max_tokens=1024,
                system=system,
                messages=[{"role": "user", "content": user}],
                tools=[{
                    "name": "emit_structured",
                    "description": f"Return a valid JSON object matching {schema.__name__}",
                    "input_schema": {"type": "object", "properties": _json_schema(schema)},
                }],
                timeout=timeout_s,
            )
        except anthropic.APITimeoutError as exc:
            raise LLMTimeoutError("LLM call exceeded budget") from exc
        except anthropic.APIError as exc:
            raise LLMProviderError(f"Anthropic API error: {exc}") from exc

        for block in resp.content:
            if getattr(block, "type", "") == "tool_use":
                return cast(dict, block.input)
        raise LLMSchemaError("LLM did not produce a structured tool call")


def _json_schema(schema: type[BaseModel]) -> dict:
    return schema.model_json_schema().get("properties", {})


def get_llm_client() -> LLMClient:
    """Factory: production Anthropic when configured, deterministic mock otherwise."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return AnthropicClient()
    return MockClient()