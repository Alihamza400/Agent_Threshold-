"""Shared test helpers for the execution adapter suite.

Unique module name (`helpers_exec`) so the non-package test directory has no
module-name collisions with other services in the monorepo run.
"""

from __future__ import annotations

from at_shared.schemas.tx import ChainId
from execution_service.validation import CHAIN_IDS

CHAIN = ChainId.BASE
EIP155 = CHAIN_IDS[CHAIN]


class FakeRPC:
    """Records broadcast calls and serves canned receipts/blocks."""

    def __init__(
        self,
        *,
        tx_hash: str = "0x" + "a" * 64,
        receipt: dict | None = None,
        block_number: int = 10,
    ) -> None:
        self.broadcast_raw: list[str] = []
        self.tx_hash = tx_hash
        self.receipt = receipt
        self.block_number = block_number

    async def send_raw_transaction(self, raw: str) -> str:
        self.broadcast_raw.append(raw)
        return self.tx_hash

    async def get_transaction_receipt(self, tx_hash: str) -> dict | None:
        return self.receipt

    async def get_block_number(self) -> int:
        return self.block_number


def receipt(block: int) -> dict:
    return {"blockNumber": hex(block)}
