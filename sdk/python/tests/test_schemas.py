"""Contract tests: the SDK's public DTOs must accept the exact payloads the
server accepts (and reject the same invalid ones). Uses the dev-only
`at-shared` schema as the source of truth (task 8.1 / FR-DATA-01 round-trip)."""

from __future__ import annotations

import json

import pytest
from agentthreshold.schemas import ChainId, Decision, DecisionType, ScreenRequest

VALID = {
    "agent_id": "01abc",
    "chain_id": "base",
    "from_address": "0x1111111111111111111111111111111111111111",
    "to_address": "0x2222222222222222222222222222222222222222",
    "value_wei": 10**16,
    "calldata": None,
    "gas_limit": 21000,
    "gas_price_wei": 10**9,
    "token": None,
    "task_context": "pay supplier",
}


def _server_schemas():
    from at_shared.schemas.tx import Decision as ServerDecision
    from at_shared.schemas.tx import ScreenRequest as ServerScreenRequest

    return ServerScreenRequest, ServerDecision


@pytest.mark.contract
def test_screen_request_parity_with_server():
    server_cls, _ = _server_schemas()
    # Same field names + types: what the server accepts, the SDK accepts.
    server = server_cls.model_validate(VALID)
    sdk = ScreenRequest.model_validate(VALID)
    assert sdk.model_dump(mode="json") == server.model_dump(mode="json")


@pytest.mark.contract
def test_decision_parity_with_server():
    _, server_cls = _server_schemas()
    body = {
        "decision": "escalate",
        "reasons": ["aggregate confidence 55.0 below escalate threshold 60.0"],
        "confidence": 55.0,
        "risk_summary": "new counterparty",
        "policy_version": 3,
        "transaction_id": "01xyz",
    }
    assert Decision.model_validate(body).model_dump(mode="json") == server_cls.model_validate(
        body
    ).model_dump(mode="json")


def test_screen_request_validates_addresses_fail_closed():
    with pytest.raises(ValueError):
        ScreenRequest.model_validate({**VALID, "from_address": "0x123"})


def test_screen_request_rejects_negative_value():
    with pytest.raises(ValueError):
        ScreenRequest.model_validate({**VALID, "value_wei": -1})


def test_screen_request_round_trips_through_json():
    request = ScreenRequest.model_validate(VALID)
    assert ScreenRequest.model_validate_json(request.model_dump_json()) == request


def test_chain_id_and_decision_serialization():
    assert ChainId("base") is ChainId.BASE
    assert DecisionType("approve") is DecisionType.APPROVE
    assert json.loads(ScreenRequest.model_validate(VALID).model_dump_json())["chain_id"] == "base"
