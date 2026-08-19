"""Fail-closed client behavior (task 8.1, SR-04):
- transport failure / 5xx / malformed body -> never signs
- REJECT / ESCALATE -> raises, never signs
- APPROVE -> calls the caller-provided signer exactly once
- non-custodial: the client never holds or derives a key
"""

from __future__ import annotations

import httpx
import pytest
import respx
from agentthreshold import (
    AgentThresholdClient,
    ScreeningEscalatedError,
    ScreeningRejectedError,
    ScreeningUnavailableError,
    TransportError,
    UnauthorizedError,
)
from agentthreshold.schemas import ChainId, ScreenRequest
from conftest import COUNTERPARTY, WALLET

SCREEN_URL = "http://screening.test/v1/transactions/screen"


def _approve_body(**overrides):
    body = {
        "decision": "approve",
        "reasons": [],
        "confidence": 90.0,
        "risk_summary": "within policy",
        "policy_version": 1,
        "transaction_id": "01approved",
    }
    body.update(overrides)
    return body


def _request():
    return ScreenRequest(
        agent_id="01agent",
        chain_id=ChainId.BASE,
        from_address=WALLET,
        to_address=COUNTERPARTY,
        value_wei=10**16,
    )


@respx.mock
def test_screen_returns_decision(client_factory):
    respx.post(SCREEN_URL).mock(return_value=httpx.Response(200, json=_approve_body()))
    decision = client_factory().screen(_request())
    assert decision.decision.value == "approve"
    assert decision.transaction_id == "01approved"


@respx.mock
def test_screen_and_sign_calls_signer_once_on_approve(client_factory):
    respx.post(SCREEN_URL).mock(return_value=httpx.Response(200, json=_approve_body()))
    calls = []

    def signer(unsigned_tx):
        calls.append(unsigned_tx)
        return {"signed": unsigned_tx}

    signed = client_factory().screen_and_sign(
        signer,
        agent_id="01agent",
        chain_id=ChainId.BASE,
        from_address=WALLET,
        to_address=COUNTERPARTY,
        value_wei=10**16,
        task_context="pay supplier",
    )
    assert len(calls) == 1
    assert signed["signed"]["from"] == WALLET
    assert signed["signed"]["value"] == 10**16


@respx.mock
def test_screen_and_sign_tx_normalizes_unsigned_tx(client_factory):
    respx.post(SCREEN_URL).mock(return_value=httpx.Response(200, json=_approve_body()))
    calls = []

    def signer(unsigned_tx):
        calls.append(unsigned_tx)
        return {"hash": "0xabc"}

    client_factory().screen_and_sign_tx(
        signer,
        {
            "from": WALLET,
            "to": COUNTERPARTY,
            "value": hex(10**16),
            "data": "0xdeadbeef",
            "gas": hex(21000),
            "gasPrice": hex(10**9),
        },
        agent_id="01agent",
        chain_id=ChainId.BASE,
    )
    sent = respx.calls.last.request.content
    payload = __import__("json").loads(sent)
    assert payload["value_wei"] == 10**16
    assert payload["gas_limit"] == 21000
    assert payload["gas_price_wei"] == 10**9
    assert payload["calldata"] == "0xdeadbeef"


@respx.mock
def test_reject_never_signs(client_factory):
    respx.post(SCREEN_URL).mock(
        return_value=httpx.Response(
            200, json=_approve_body(decision="reject", reasons=["over limit"], confidence=0.0)
        )
    )
    signed = []

    with pytest.raises(ScreeningRejectedError) as exc:
        client_factory().screen_and_sign(
            lambda tx: signed.append(tx),
            agent_id="01agent",
            chain_id=ChainId.BASE,
            from_address=WALLET,
            to_address=COUNTERPARTY,
            value_wei=10**16,
        )
    assert signed == []
    assert "reject" in str(exc.value)
    assert exc.value.decision.transaction_id == "01approved"


@respx.mock
def test_escalate_never_signs(client_factory):
    respx.post(SCREEN_URL).mock(
        return_value=httpx.Response(
            200,
            json=_approve_body(decision="escalate", reasons=["new counterparty"], confidence=45.0),
        )
    )
    with pytest.raises(ScreeningEscalatedError):
        client_factory().screen_and_sign(
            lambda tx: tx,
            agent_id="01agent",
            chain_id=ChainId.BASE,
            from_address=WALLET,
            to_address=COUNTERPARTY,
            value_wei=10**16,
        )


@respx.mock
def test_transport_failure_fails_closed(client_factory):
    respx.post(SCREEN_URL).mock(side_effect=httpx.ConnectError("no route"))
    with pytest.raises(TransportError):
        client_factory().screen(_request())


@respx.mock
def test_http_500_fails_closed(client_factory):
    respx.post(SCREEN_URL).mock(return_value=httpx.Response(503, text="unavailable"))
    with pytest.raises(ScreeningUnavailableError):
        client_factory().screen(_request())


@respx.mock
def test_401_raises_unauthorized(client_factory):
    respx.post(SCREEN_URL).mock(return_value=httpx.Response(401, text="Invalid API key"))
    with pytest.raises(UnauthorizedError):
        client_factory().screen(_request())


@respx.mock
def test_malformed_body_fails_closed(client_factory):
    respx.post(SCREEN_URL).mock(
        return_value=httpx.Response(200, json={"decision": "not-a-decision"})
    )
    with pytest.raises(ScreeningUnavailableError):
        client_factory().screen(_request())


@respx.mock
def test_429_fails_closed(client_factory):
    respx.post(SCREEN_URL).mock(return_value=httpx.Response(429, text="slow down"))
    with pytest.raises(ScreeningUnavailableError):
        client_factory().screen(_request())


@respx.mock
def test_retries_transport_errors_then_succeeds(client_factory):
    route = respx.post(SCREEN_URL)
    route.side_effect = [
        httpx.ConnectError("flaky"),
        httpx.Response(200, json=_approve_body()),
    ]
    decision = client_factory(max_retries=1).screen(_request())
    assert decision.decision.value == "approve"
    assert route.call_count == 2


def test_requires_credentials(client_factory):
    with pytest.raises(ValueError):
        AgentThresholdClient(base_url="", api_key="x")
    with pytest.raises(ValueError):
        AgentThresholdClient(base_url="http://x", api_key="")


def test_client_is_context_manager_and_closes(client_factory):
    with client_factory() as client:
        assert client.base_url == "http://screening.test"
