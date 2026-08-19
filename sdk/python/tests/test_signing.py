"""Unsigned-tx normalization tests (non-custodial wrapping, task 8.1)."""

from __future__ import annotations

import pytest
from agentthreshold.schemas import ChainId
from agentthreshold.signing import InvalidUnsignedTxError, unsigned_tx_to_screen_request
from conftest import COUNTERPARTY, WALLET


def test_maps_evm_style_keys():
    req = unsigned_tx_to_screen_request(
        {
            "from": WALLET,
            "to": COUNTERPARTY,
            "value": "0x2386f26fc10000",  # 10^16
            "data": "0xdeadbeef",
            "gas": 21000,
            "gasPrice": "0x3b9aca00",  # 10^9
        },
        agent_id="01agent",
        chain_id=ChainId.BASE,
        task_context="swap",
    )
    assert req.value_wei == 10**16
    assert req.gas_limit == 21000
    assert req.gas_price_wei == 10**9
    assert req.calldata == "0xdeadbeef"
    assert req.task_context == "swap"


def test_minimal_tx_ok_without_optional_fields():
    req = unsigned_tx_to_screen_request(
        {"from": WALLET, "value": 1},
        agent_id="01agent",
        chain_id=ChainId.ETHEREUM,
    )
    assert req.to_address is None
    assert req.gas_limit is None
    assert req.calldata is None


def test_missing_from_fails_closed():
    with pytest.raises(InvalidUnsignedTxError):
        unsigned_tx_to_screen_request(
            {"to": COUNTERPARTY, "value": 1}, agent_id="01agent", chain_id=ChainId.BASE
        )


def test_missing_value_fails_closed():
    with pytest.raises(InvalidUnsignedTxError):
        unsigned_tx_to_screen_request({"from": WALLET}, agent_id="01agent", chain_id=ChainId.BASE)


@pytest.mark.parametrize("bad", ["0xzzz", "not-a-number", True, 1.5])
def test_non_integer_value_fails_closed(bad):
    with pytest.raises(InvalidUnsignedTxError):
        unsigned_tx_to_screen_request(
            {"from": WALLET, "value": bad}, agent_id="01agent", chain_id=ChainId.BASE
        )


def test_invalid_from_address_fails_closed():
    with pytest.raises(InvalidUnsignedTxError):
        unsigned_tx_to_screen_request(
            {"from": "0x123", "value": 1}, agent_id="01agent", chain_id=ChainId.BASE
        )
