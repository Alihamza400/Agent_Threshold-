"""Confirmation + reorg monitoring (task 8.5, TRD 5.6/5.9).

The worker polls broadcast transactions for receipts and marks them `executed`
once the per-chain confirmation depth is reached. Confirmed transactions are
re-verified within a reorg-watch window: if the receipt's block changes or
disappears, the record is flagged `reorged` (the plan calls for a flag, not an
automatic re-broadcast — re-broadcast requires a fresh decision).

All RPC failures are tolerated here (the worker loop survives); the rows stay
in `broadcast`/`executed` and are retried on the next tick.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from at_shared.models import Transaction
from blockchain.config import ChainConfig
from blockchain.errors import RPCError
from blockchain.rpc import RPCClient
from sqlalchemy import select
from sqlalchemy.orm import Session

logger = logging.getLogger("execution_service.monitor")

CONFIRMED = ("executed",)


def _block_number(receipt: dict) -> int | None:
    try:
        value = receipt.get("blockNumber")
        return int(value, 16) if value else None
    except (TypeError, ValueError):
        return None


class ConfirmMonitor:
    def __init__(
        self,
        *,
        session_factory: Callable[[], Session],
        chain_resolver: Callable[[str], ChainConfig | None],
        rpc_factory: Callable[[ChainConfig], RPCClient],
        reorg_watch_seconds: int = 6 * 3600,
    ) -> None:
        self._session_factory = session_factory
        self._chain_resolver = chain_resolver
        self._rpc_factory = rpc_factory
        self._reorg_watch = reorg_watch_seconds

    # ------------------------------------------------------------ broadcast
    async def confirm_broadcasts(self, limit: int = 200) -> int:
        """Mark broadcast txs `executed` once confirmations are reached.

        Returns the number newly executed.
        """
        confirmed = 0
        with self._session_factory() as session:
            rows = session.scalars(
                select(Transaction)
                .where(Transaction.status == "broadcast", Transaction.tx_hash.is_not(None))
                .order_by(Transaction.broadcast_at.asc())
                .limit(limit)
            ).all()
            for tx in rows:
                chain = self._chain_resolver(tx.chain_id)
                if chain is None:
                    continue
                rpc = self._rpc_factory(chain)
                try:
                    receipt = await rpc.get_transaction_receipt(tx.tx_hash)
                    block = _block_number(receipt) if receipt else None
                    if block is None:
                        continue  # still pending; re-check next tick
                    tip = await rpc.get_block_number()
                except RPCError:
                    logger.warning("receipt poll failed for %s; retrying", tx.id)
                    continue
                if tip - block >= chain.confirmations:
                    now = datetime.now(UTC)
                    tx.status = "executed"
                    tx.block_number = block
                    tx.confirmed_at = now
                    tx.executed_at = now
                    confirmed += 1
            session.commit()
        return confirmed

    # ------------------------------------------------------------------ reorg
    async def detect_reorgs(self, limit: int = 200) -> list[str]:
        """Flag executed txs whose confirmed block was orphaned (reorg).

        Returns the ids flagged `reorged`. A reorg is detected when the
        receipt's block number differs from the one we recorded, or the
        receipt is gone entirely. A block that is no longer canonical is the
        signal; the record is flagged, not re-broadcast.
        """
        flagged: list[str] = []
        cutoff = datetime.now(UTC) - timedelta(seconds=self._reorg_watch)
        with self._session_factory() as session:
            rows = session.scalars(
                select(Transaction)
                .where(
                    Transaction.status == "executed",
                    Transaction.confirmed_at.is_not(None),
                    Transaction.confirmed_at >= cutoff,
                    Transaction.tx_hash.is_not(None),
                )
                .order_by(Transaction.confirmed_at.asc())
                .limit(limit)
            ).all()
            for tx in rows:
                chain = self._chain_resolver(tx.chain_id)
                if chain is None:
                    continue
                rpc = self._rpc_factory(chain)
                try:
                    receipt = await rpc.get_transaction_receipt(tx.tx_hash)
                    block = _block_number(receipt) if receipt else None
                except RPCError:
                    continue
                reorged = block is None or (
                    tx.block_number is not None and block != tx.block_number
                )
                if reorged:
                    tx.status = "reorged"
                    tx.reorged_at = datetime.now(UTC)
                    flagged.append(tx.id)
            session.commit()
        if flagged:
            logger.warning("reorg flagged for transactions: %s", flagged)
        return flagged
