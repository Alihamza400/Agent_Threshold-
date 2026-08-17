"""LLM client, agents, and prompt registry tests (FR-AI-01, FR-AI-03, TRD 4.6)."""

from __future__ import annotations

import pytest
from screening_agents.classifier import IntentClassifier
from screening_agents.errors import (
    CircuitOpenError,
    LLMSchemaError,
    ScreeningAgentError,
)
from screening_agents.escalation import EscalationDrafter
from screening_agents.interpreter import SimulationInterpreter
from screening_agents.llm import MockClient
from screening_agents.prompts import get_prompt
from screening_agents.schemas import ActionClass, RiskLevel


@pytest.fixture()
def mock_llm() -> MockClient:
    return MockClient()


def test_prompt_registry_versions_present():
    for name in ("classifier", "interpreter", "escalation"):
        system, version = get_prompt(name)
        assert system and version.startswith(f"{name}.")
    assert get_prompt("classifier")[1] == "classifier.v1"


def test_prompt_registry_unknown_fails_closed():
    with pytest.raises(ScreeningAgentError):
        get_prompt("classifier", version="classifier.v99")


def test_classifier_mock_swap(mock_llm):
    result = IntentClassifier(mock_llm).classify("perform a token swap of ETH to USDC")
    assert result.action_class == ActionClass.SWAP
    assert 0.0 <= result.confidence <= 1.0


def test_classifier_mock_approval(mock_llm):
    result = IntentClassifier(mock_llm).classify("approve unlimited USDC spending")
    assert result.action_class == ActionClass.APPROVAL


def test_classifier_mock_withdraw(mock_llm):
    result = IntentClassifier(mock_llm).classify("withdraw rewards to treasury")
    assert result.action_class == ActionClass.WITHDRAW


def test_interpreter_mock_balance_drain(mock_llm):
    result = SimulationInterpreter(mock_llm).interpret(
        {"before": {"ETH": "10"}, "after": {"ETH": "0"}}
    )
    assert result.balance_drain is False  # mock only flags keyword


def test_interpreter_mock_drain_keyword(mock_llm):
    result = SimulationInterpreter(mock_llm).interpret(
        {"note": "approve unlimited -> drain detected"}
    )
    assert result.balance_drain is True
    assert result.risk_level == RiskLevel.CRITICAL


def test_escalation_drafter_mock(mock_llm):
    result = EscalationDrafter(mock_llm).draft(
        agent_name="demo-hedge",
        action_summary="transfer 10 ETH to new address",
        anomaly_factors=["new counterparty"],
        policy_reasons=["first transaction to previously unseen counterparty"],
    )
    assert result.title
    assert result.summary
    assert "unverified counterparty" in result.key_risks


def test_mock_outputs_are_schema_valid(mock_llm):
    """Strict schema validation is enforced on every LLM response."""
    result = IntentClassifier(mock_llm).classify("swap tokens")
    assert isinstance(result.action_class, ActionClass)


def test_circuit_breaker_trips_and_fails_closed():
    from screening_agents.schemas import IntentClassification

    client = MockClient()
    # trip the client's own circuit breaker
    for _ in range(3):
        client.circuit.record_failure()
    assert client.circuit.is_open() is True
    with pytest.raises(CircuitOpenError):
        client.complete("s", "u", IntentClassification)


def test_malformed_schema_fails_closed():
    class BadClient(MockClient):
        def _complete(self, system, user, schema):
            return {"action_class": "not-a-real-class", "confidence": 9}

    with pytest.raises(LLMSchemaError):
        BadClient().complete("s", "u", __import__("screening_agents.schemas", fromlist=["IntentClassification"]).IntentClassification)