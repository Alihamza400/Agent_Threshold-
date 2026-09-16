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


def test_classifier_transfer_action(mock_llm):
    result = IntentClassifier(mock_llm).classify("send 5 ETH to alice")
    assert result.action_class == ActionClass.TRANSFER


def test_classifier_contract_interaction(mock_llm):
    result = IntentClassifier(mock_llm).classify("deploy a new token contract")
    assert result.action_class == ActionClass.CONTRACT_INTERACTION


def test_classifier_none_task_context(mock_llm):
    result = IntentClassifier(mock_llm).classify(None)
    assert isinstance(result.action_class, ActionClass)
    assert 0.0 <= result.confidence <= 1.0


def test_classifier_empty_task_context(mock_llm):
    result = IntentClassifier(mock_llm).classify("")
    assert isinstance(result.action_class, ActionClass)


def test_classifier_with_tool_call_history(mock_llm):
    result = IntentClassifier(mock_llm).classify(
        "swap tokens", tool_call_history=["approve_token", "swap_exact"]
    )
    assert result.action_class == ActionClass.SWAP


def test_interpreter_empty_state_diff(mock_llm):
    result = SimulationInterpreter(mock_llm).interpret({})
    assert isinstance(result.risk_level, RiskLevel)
    assert isinstance(result.balance_drain, bool)


def test_interpreter_non_drain_risk(mock_llm):
    result = SimulationInterpreter(mock_llm).interpret(
        {"before": {"USDC": "1000"}, "after": {"USDC": "950"}}
    )
    assert result.balance_drain is False
    assert result.risk_level in (RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL)


def test_escalation_drafter_empty_anomaly_factors(mock_llm):
    result = EscalationDrafter(mock_llm).draft(
        agent_name="test-agent",
        action_summary="simple transfer",
        anomaly_factors=[],
        policy_reasons=[],
    )
    assert result.title
    assert result.summary
    assert isinstance(result.recommended_action.value, str)


def test_escalation_drafter_prompt_version(mock_llm):
    drafter = EscalationDrafter(mock_llm)
    assert drafter.prompt_version.startswith("escalation.")


def test_classifier_prompt_version(mock_llm):
    classifier = IntentClassifier(mock_llm)
    assert classifier.prompt_version.startswith("classifier.")


def test_interpreter_prompt_version(mock_llm):
    interpreter = SimulationInterpreter(mock_llm)
    assert interpreter.prompt_version.startswith("interpreter.")


def test_circuit_breaker_resets_after_success(mock_llm):
    client = MockClient()
    for _ in range(2):
        client.circuit.record_failure()
    assert client.circuit.is_open() is False  # below threshold
    client.circuit.record_success()
    assert client.circuit._consecutive_failures == 0


def test_circuit_breaker_does_not_trip_below_threshold(mock_llm):
    from screening_agents.schemas import IntentClassification

    client = MockClient()
    client.circuit.record_failure()
    client.circuit.record_failure()
    assert client.circuit.is_open() is False
    result = client.complete("s", "u swap tokens", IntentClassification)
    assert result.action_class == ActionClass.SWAP


def test_schema_error_records_failure(mock_llm):
    class BadClient(MockClient):
        def _complete(self, system, user, schema):
            return {"action_class": "bogus", "confidence": 0.5}

    client = BadClient()
    with pytest.raises(LLMSchemaError):
        client.complete("s", "u", __import__("screening_agents.schemas", fromlist=["IntentClassification"]).IntentClassification)
    assert client.circuit._consecutive_failures == 1


def test_interpreter_risk_level_valid_enum(mock_llm):
    result = SimulationInterpreter(mock_llm).interpret({"data": "test"})
    assert result.risk_level in (RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL)


def test_escalation_draft_risk_tags_present(mock_llm):
    result = SimulationInterpreter(mock_llm).interpret(
        {"note": "drain detected in swap"}
    )
    assert isinstance(result.risk_tags, list)


def test_mock_client_model_name():
    client = MockClient()
    assert client.model == "mock-deterministic-v1"


def test_mock_client_timeout_inherited():
    client = MockClient(timeout_ms=500)
    assert client.timeout_ms == 500
