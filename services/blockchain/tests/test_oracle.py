"""Price oracle tests (5.7): Chainlink decode + fallback + USD conversion."""

from __future__ import annotations

import httpx
import pytest
import respx
from at_shared.schemas.tx import ChainId
from blockchain.config import ChainConfig
from blockchain.errors import NoProviderConfiguredError, OracleError
from blockchain.oracle import ChainlinkOracle, StaticOracle, build_oracle
from blockchain.rpc import RPCClient

AGG = "0x5f4ec3df9cbd43714fe2740f5e3616155c5b8419"

# latestRoundData: roundId(0), answer(2000e8), startedAt, updatedAt, answeredInRound
def _round_data() -> str:
    answer = hex(2000 * 10**8)[2:].zfill(64)
    return "0x" + "0" * 64 + answer + "0" * 64 * 2 + "0" * 64


def _json_response(result):
    return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})


def _chain() -> ChainConfig:
    return ChainConfig(ChainId.ETHEREUM, ["https://rpc.test"], 12, eth_usd_aggregator=AGG)


@pytest.mark.asyncio
async def test_chainlink_price_decoded():
    async with respx.mock:
        # route both eth_call requests
        respx.post("https://rpc.test").mock(
            side_effect=[
                _json_response(_round_data()),
                _json_response("0x" + "00" * 31 + "08"),  # decimals() = 8
            ]
        )
        client = RPCClient(_chain())
        oracle = ChainlinkOracle(client)
        price = await oracle.price_usd_per_native(_chain())
        assert price == 2000.0


@pytest.mark.asyncio
async def test_chainlink_usd_value():
    async with respx.mock:
        respx.post("https://rpc.test").mock(
            side_effect=[
                _json_response(_round_data()),
                _json_response("0x" + "00" * 31 + "08"),
            ]
        )
        oracle = ChainlinkOracle(RPCClient(_chain()))
        usd = await oracle.usd_value(_chain(), 10**18)  # 1 ETH
        assert usd == pytest.approx(2000.0)


@pytest.mark.asyncio
async def test_static_oracle_fallback():
    oracle = StaticOracle(price_usd=1800.0)
    assert await oracle.price_usd_per_native(_chain()) == 1800.0
    assert await oracle.usd_value(_chain(), 10**18) == 1800.0


def test_build_oracle_chooses_chainlink_when_configured():
    oracle = build_oracle(RPCClient(_chain()), _chain(), static_price=1.0)
    assert isinstance(oracle, ChainlinkOracle)


def test_build_oracle_uses_static_without_aggregator():
    chain_no_agg = ChainConfig(ChainId.BASE, ["https://rpc.test"], 2)
    oracle = build_oracle(RPCClient(chain_no_agg), chain_no_agg, static_price=1.0)
    assert isinstance(oracle, StaticOracle)


def test_build_oracle_fails_closed_without_any_source():
    chain_no_agg = ChainConfig(ChainId.BASE, ["https://rpc.test"], 2)
    with pytest.raises(NoProviderConfiguredError):
        build_oracle(RPCClient(chain_no_agg), chain_no_agg, static_price=None)


@pytest.mark.asyncio
async def test_non_positive_price_fails_closed():
    zero_answer = "0x" + "0" * 64 + "0" * 64 + "0" * 128
    async with respx.mock:
        respx.post("https://rpc.test").mock(
            side_effect=[_json_response(zero_answer), _json_response("0x" + "00" * 31 + "08")]
        )
        oracle = ChainlinkOracle(RPCClient(_chain()))
        with pytest.raises(OracleError):
            await oracle.price_usd_per_native(_chain())