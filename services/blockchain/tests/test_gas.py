"""Gas estimation + policy ceiling tests (FR-CHAIN-02)."""

from __future__ import annotations

import httpx
import pytest
import respx
from blockchain.errors import GasExceedsCeilingError
from blockchain.gas import estimate_and_check, gas_with_buffer, validate_gas_ceiling
from blockchain.rpc import RPCClient


def _json_response(result):
    return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})


def test_gas_buffer_applies_percentage():
    assert gas_with_buffer(100_000, buffer_pct=20.0) == 120_000
    assert gas_with_buffer(0, buffer_pct=20.0) == 0


def test_gas_buffer_defaults_to_settings():
    # default 20% from Settings
    assert gas_with_buffer(1_000_000) == 1_200_000


def test_validate_gas_ceiling():
    assert validate_gas_ceiling(100, None) is True
    assert validate_gas_ceiling(99, 100) is True
    assert validate_gas_ceiling(100, 100) is True
    assert validate_gas_ceiling(101, 100) is False


@pytest.mark.asyncio
async def test_estimate_within_ceiling(chain):
    async with respx.mock:
        respx.post(chain.rpc_urls[0]).mock(return_value=_json_response(hex(100_000)))
        respx.post(chain.rpc_urls[1]).mock(return_value=_json_response(hex(100_000)))
        client = RPCClient(chain)
        gas, ceiling_used = await estimate_and_check(
            client, {"from": "0x1", "to": "0x2"}, ceiling=200_000
        )
        assert gas == 120_000  # 100k + 20% buffer
        assert ceiling_used is False


@pytest.mark.asyncio
async def test_estimate_over_ceiling_fails_closed(chain):
    async with respx.mock:
        respx.post(chain.rpc_urls[0]).mock(return_value=_json_response(hex(200_000)))
        respx.post(chain.rpc_urls[1]).mock(return_value=_json_response(hex(200_000)))
        client = RPCClient(chain)
        with pytest.raises(GasExceedsCeilingError):
            await estimate_and_check(client, {"from": "0x1", "to": "0x2"}, ceiling=200_000)
            # buffered 240k > ceiling 200k