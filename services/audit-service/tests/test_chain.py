"""AnchorChainClient tests: ABI encoding, RPC reads, signing, confirmations."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx
import rlp
from at_shared.schemas.tx import ChainId
from audit_service.chain import AnchorChainClient, encode_anchor_batch, encode_get_batch_root
from audit_service.errors import (
    AnchorConfigurationError,
    AnchorRevertedError,
    AnchorSubmissionError,
)
from blockchain.config import ChainConfig
from eth_hash.auto import keccak

RPC_URL = "http://rpc.test:8545"
CONTRACT = "0x9fE46736679d2D9a65F0992F2272dE9f3c7fa6e0"
PK = "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d"
ROOT = bytes.fromhex("b0cb5b3f0776b1932410c3ffbb811f62a8f26a361d22b818e4e92965a6014da5")


def make_chain(**kw) -> AnchorChainClient:
    chain = ChainConfig(ChainId.ETHEREUM, [RPC_URL], 1)
    kw.setdefault("chain", chain)
    kw.setdefault("contract", CONTRACT)
    kw.setdefault("private_key", PK)
    kw.setdefault("eip155_chain_id", 31337)
    kw.setdefault("confirmations", 1)
    kw.setdefault("poll_seconds", 0.001)
    kw.setdefault("confirm_timeout_seconds", 2.0)
    return AnchorChainClient(**kw)


def _rpc_result(method: str, params: list[Any]) -> Any:
    if method == "eth_getTransactionCount":
        return "0x0"
    if method == "eth_estimateGas":
        return "0x5208"
    if method == "eth_gasPrice":
        return "0x77359400"
    if method == "eth_blockNumber":
        return "0x65"
    if method == "eth_call":
        data = params[0]["data"]
        if data.startswith(keccak(b"lastBatchId()")[:4].hex()):
            return "0x" + (7).to_bytes(32, "big").hex()
        return "0x" + ROOT.hex()
    if method == "eth_getTransactionReceipt":
        return {
            "blockNumber": "0x64",
            "status": "0x1",
            "transactionHash": "0xabc",
        }
    if method == "eth_sendRawTransaction":
        return "0xabc"
    return None


def _install_routes() -> respx.MockRouter:
    router = respx.mock(assert_all_called=False)

    def handler(request) -> respx.Response:
        body = json.loads(request.content)
        result = _rpc_result(body["method"], body["params"])
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})

    router.post(RPC_URL).mock(side_effect=handler)
    return router


def test_encode_anchor_batch_matches_solidity_selector():
    data = encode_anchor_batch(7, ROOT)
    assert data.startswith("f4824b8e")  # anchorBatch(uint256,bytes32)
    assert data[8:] == (7).to_bytes(32, "big").hex() + ROOT.hex()


def test_encode_get_batch_root_selector():
    assert encode_get_batch_root(7).startswith("e2350d63")


def test_missing_private_key_fails_closed():
    with pytest.raises(AnchorConfigurationError):
        make_chain(private_key="")


@pytest.mark.asyncio
async def test_last_batch_id_reads_chain():
    with _install_routes():
        chain = make_chain()
        assert await chain.last_batch_id() == 7


@pytest.mark.asyncio
async def test_anchored_root_reads_chain():
    with _install_routes():
        chain = make_chain()
        assert await chain.anchored_root(7) == ROOT


@pytest.mark.asyncio
async def test_submit_signs_and_broadcasts_valid_tx():
    captured: dict[str, Any] = {}
    router = _install_routes()
    with router:
        chain = make_chain()
        original = router.routes[0].side_effect

        async def patched(request):
            body = json.loads(request.content)
            if body["method"] == "eth_sendRawTransaction":
                captured["raw"] = body["params"][0]
            return original(request)

        router.routes[0].side_effect = patched
        assert await chain.submit(7, ROOT) == "0xabc"

    nonce, gas_price, gas, to, value, data, _v, _r, _s = rlp.decode(
        bytes.fromhex(captured["raw"][2:])
    )
    assert to == bytes.fromhex(CONTRACT[2:])
    assert data.hex() == encode_anchor_batch(7, ROOT)
    assert int.from_bytes(nonce, "big") == 0
    assert value == b""  # no value transferred
    assert int.from_bytes(gas_price, "big") == 0x77359400
    assert int.from_bytes(gas, "big") >= 0x5208  # buffered above the estimate


@pytest.mark.asyncio
async def test_reverted_tx_raises():
    def handler(request) -> respx.Response:
        body = json.loads(request.content)
        if body["method"] == "eth_getTransactionReceipt":
            return httpx.Response(
                200,
                json={"jsonrpc": "2.0", "id": 1, "result": {"blockNumber": "0x64", "status": "0x0"}},
            )
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": 1, "result": _rpc_result(body["method"], body["params"])},
        )

    with respx.mock(assert_all_called=False) as router:
        router.post(RPC_URL).mock(side_effect=handler)
        chain = make_chain()
        with pytest.raises(AnchorRevertedError):
            await chain.submit(7, ROOT)


@pytest.mark.asyncio
async def test_unconfirmed_tx_raises():
    def handler(request) -> respx.Response:
        body = json.loads(request.content)
        if body["method"] == "eth_getTransactionReceipt":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": None})
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": 1, "result": _rpc_result(body["method"], body["params"])},
        )

    with respx.mock(assert_all_called=False) as router:
        router.post(RPC_URL).mock(side_effect=handler)
        chain = make_chain()
        with pytest.raises(AnchorSubmissionError):
            await chain.submit(7, ROOT)