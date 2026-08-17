"""Multi-provider RPC cross-check tests (5.1, 5.4; fail-closed)."""

from __future__ import annotations

import httpx
import pytest
import respx
from at_shared.schemas.tx import ChainId
from blockchain.config import ChainConfig
from blockchain.errors import CrossCheckMismatchError, NoProviderConfiguredError, RPCError
from blockchain.rpc import RPCClient


def _json_response(result):
    return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})


@pytest.mark.asyncio
async def test_call_returns_primary_when_providers_agree(chain):
    async with respx.mock:
        respx.post(chain.rpc_urls[0]).mock(return_value=_json_response("0x1"))
        respx.post(chain.rpc_urls[1]).mock(return_value=_json_response("0x1"))
        client = RPCClient(chain)
        balance = await client.get_balance("0x1111111111111111111111111111111111111111")
        assert balance == 1


@pytest.mark.asyncio
async def test_cross_check_mismatch_fails_closed(chain):
    """Primary and fallback disagree -> CrossCheckMismatchError (malicious RPC)."""
    async with respx.mock:
        respx.post(chain.rpc_urls[0]).mock(return_value=_json_response("0x1234"))
        respx.post(chain.rpc_urls[1]).mock(return_value=_json_response("0x9999"))
        client = RPCClient(chain)
        with pytest.raises(CrossCheckMismatchError):
            await client.get_balance("0x1111111111111111111111111111111111111111")


@pytest.mark.asyncio
async def test_no_fallback_skips_cross_check(chain_single):
    async with respx.mock:
        respx.post(chain_single.rpc_urls[0]).mock(return_value=_json_response("0x2a"))
        client = RPCClient(chain_single)
        assert await client.get_balance("0x1111111111111111111111111111111111111111") == 42


@pytest.mark.asyncio
async def test_non_cross_checked_methods_not_compared(chain):
    """eth_getTransactionCount is excluded from cross-check (pending drifts)."""
    async with respx.mock:
        respx.post(chain.rpc_urls[0]).mock(return_value=_json_response("0x5"))
        respx.post(chain.rpc_urls[1]).mock(return_value=_json_response("0x7"))
        client = RPCClient(chain)
        assert await client.get_transaction_count("0x1111111111111111111111111111111111111111") == 5


@pytest.mark.asyncio
async def test_no_provider_configured():
    empty = ChainConfig(ChainId.BASE, [], confirmations=2)
    client = RPCClient(empty)
    with pytest.raises(NoProviderConfiguredError):
        await client.get_balance("0x1111111111111111111111111111111111111111")


@pytest.mark.asyncio
async def test_rpc_error_raises(chain):
    async with respx.mock:
        respx.post(chain.rpc_urls[0]).mock(
            return_value=httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": "boom"}})
        )
        client = RPCClient(chain)
        with pytest.raises(RPCError):
            await client.get_balance("0x1111111111111111111111111111111111111111")


@pytest.mark.asyncio
async def test_http_failure_raises(chain):
    async with respx.mock:
        respx.post(chain.rpc_urls[0]).mock(return_value=httpx.Response(503, text="unavailable"))
        client = RPCClient(chain)
        with pytest.raises(RPCError):
            await client.get_balance("0x1111111111111111111111111111111111111111")