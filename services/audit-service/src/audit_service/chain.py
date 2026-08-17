"""Read/verify/write against the AuditAnchor contract (Phase 6.6).

The client submits `anchorBatch(uint256, bytes32)` from a configured anchor
EOA, waits for confirmations, and exposes deterministic reads used for the
fail-closed verification (the chain must echo back exactly the root we sent).
"""

from __future__ import annotations

import asyncio
import time

from blockchain.config import ChainConfig
from blockchain.rpc import RPCClient
from eth_account import Account
from eth_account.signers.local import LocalAccount
from eth_hash.auto import keccak
from eth_utils import to_checksum_address

from audit_service.errors import (
    AnchorConfigurationError,
    AnchorRevertedError,
    AnchorSubmissionError,
    AnchorVerificationError,
)

_ANCHOR_BATCH_SIG = "anchorBatch(uint256,bytes32)"
_GET_BATCH_ROOT_SIG = "getBatchRoot(uint256)"
_LAST_BATCH_ID_SIG = "lastBatchId()"


def _selector(signature: str) -> bytes:
    return keccak(signature.encode())[:4]


def encode_anchor_batch(batch_id: int, root: bytes) -> str:
    """ABI-encode `anchorBatch(uint256,bytes32)` without a full ABI lib."""
    return (_selector(_ANCHOR_BATCH_SIG) + batch_id.to_bytes(32, "big") + root).hex()


def encode_get_batch_root(batch_id: int) -> str:
    return (_selector(_GET_BATCH_ROOT_SIG) + batch_id.to_bytes(32, "big")).hex()


class AnchorChainClient:
    """Thin typed wrapper over RPCClient for the AuditAnchor contract."""

    def __init__(
        self,
        *,
        chain: ChainConfig,
        contract: str,
        private_key: str,
        eip155_chain_id: int,
        confirmations: int = 1,
        gas_buffer_pct: float = 20.0,
        poll_seconds: float = 1.0,
        confirm_timeout_seconds: float = 120.0,
        rpc: RPCClient | None = None,
    ) -> None:
        if not chain.rpc_urls:
            raise AnchorConfigurationError("no RPC endpoint configured for anchoring")
        if not contract:
            raise AnchorConfigurationError("anchor contract address not configured")
        if not private_key:
            raise AnchorConfigurationError("anchor wallet private key not configured")
        self.chain = chain
        # eth-account demands an EIP-55 checksummed `to`; env config is often
        # all-lowercase (e.g. from a deployment broadcast log).
        self.contract = to_checksum_address(contract)
        self.eip155_chain_id = eip155_chain_id
        self.confirmations = confirmations
        self._gas_buffer = 1.0 + gas_buffer_pct / 100.0
        self._poll = poll_seconds
        self._confirm_timeout = confirm_timeout_seconds
        self.signer: LocalAccount = Account.from_key(private_key)
        self._rpc = rpc or RPCClient(chain)

    @property
    def address(self) -> str:
        return self.signer.address

    async def aclose(self) -> None:
        await self._rpc.aclose()

    async def last_batch_id(self) -> int:
        raw = await self._rpc.call_contract(
            {"to": self.contract, "data": _selector(_LAST_BATCH_ID_SIG).hex()}
        )
        return int(raw, 16)

    async def anchored_root(self, batch_id: int) -> bytes:
        raw = await self._rpc.call_contract(
            {"to": self.contract, "data": encode_get_batch_root(batch_id)}
        )
        return bytes.fromhex(raw[2:])

    async def submit(self, batch_id: int, root: bytes) -> str:
        """Sign, broadcast, and wait for `anchorBatch(batch_id, root)`.

        Returns the transaction hash once the tx is `confirmations` deep and
        confirmed with status 1. Any failure raises so the batcher retains the
        pending batch (fail-closed).
        """
        data = encode_anchor_batch(batch_id, root)
        nonce = await self._rpc.get_transaction_count(self.signer.address, "pending")
        estimate = await self._rpc.estimate_gas(
            {"from": self.signer.address, "to": self.contract, "data": data}
        )
        gas_price = int(await self._rpc.call("eth_gasPrice", []), 16)
        tx = {
            "from": self.signer.address,
            "to": self.contract,
            "nonce": nonce,
            "gas": int(estimate * self._gas_buffer),
            "gasPrice": gas_price,
            "value": 0,
            "data": data,
            "chainId": self.eip155_chain_id,
        }
        signed = self.signer.sign_transaction(tx)
        tx_hash = await self._rpc.send_raw_transaction("0x" + signed.raw_transaction.hex())
        await self._wait_confirmed(batch_id, root, tx_hash)
        return tx_hash

    async def _wait_confirmed(self, batch_id: int, root: bytes, tx_hash: str) -> None:
        deadline = time.monotonic() + self._confirm_timeout
        while True:
            receipt = await self._rpc.get_transaction_receipt(tx_hash)
            if receipt is not None:
                if receipt.get("status") == "0x0":
                    raise AnchorRevertedError(batch_id, root, 1, "transaction reverted")
                depth = await self._rpc.get_block_number() - int(
                    receipt["blockNumber"], 16
                ) + 1
                if depth >= self.confirmations:
                    return
            if time.monotonic() > deadline:
                raise AnchorSubmissionError(
                    batch_id, root, 1, f"tx {tx_hash} not confirmed in time"
                )
            await asyncio.sleep(self._poll)

    async def verify_anchored(self, batch_id: int, root: bytes) -> None:
        anchored = await self.anchored_root(batch_id)
        if anchored != root:
            raise AnchorVerificationError(
                batch_id, root, 1, f"expected {root.hex()} got {anchored.hex()}"
            )