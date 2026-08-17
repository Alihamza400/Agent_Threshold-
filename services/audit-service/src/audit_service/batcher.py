"""Async anchor batching worker (6.6): flush every 1,000 records or 15 minutes.

Runs off the hot path — callers only append a 32-byte leaf and the worker
owns submission. Fail-closed contract (FR-AUDIT-01):

  * A flush only clears the buffer after the chain echoes back exactly the
    root we submitted for the expected batch id.
  * Submission is retried with exponential backoff; on final failure the
    pending batch is RETAINED so no audit record is ever silently dropped.
  * Ambiguous failures (e.g. confirmation timeout while the tx actually
    landed) are resolved by verifying the on-chain root before retrying, so
    a later attempt cannot double-anchor a stale batch id.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

from audit_service.errors import AnchorSubmissionError, MerkleError
from audit_service.merkle import LEAF_BYTES, merkle_root

logger = logging.getLogger("audit_service.batcher")

Clock = Callable[[], float]
Sleeper = Callable[[float], Awaitable[None]]


class AnchorBatcher:
    def __init__(
        self,
        *,
        chain: object,
        max_records: int = 1000,
        interval_seconds: float = 900.0,
        max_attempts: int = 5,
        backoff_base_seconds: float = 5.0,
        clock: Clock = time.monotonic,
        sleep: Sleeper = asyncio.sleep,
    ) -> None:
        self._chain = chain
        self.max_records = max_records
        self.interval_seconds = interval_seconds
        self.max_attempts = max_attempts
        self._backoff_base = backoff_base_seconds
        self._clock = clock
        self._sleep = sleep
        self._leaves: list[bytes] = []
        self._first_at: float | None = None
        self._last_anchored_batch_id: int | None = None
        self._stopped = False

    @property
    def pending_count(self) -> int:
        return len(self._leaves)

    @property
    def last_anchored_batch_id(self) -> int | None:
        return self._last_anchored_batch_id

    async def add(self, leaf: bytes) -> None:
        """Append a record digest; auto-flush when the record threshold hits."""
        if len(leaf) != LEAF_BYTES:
            raise MerkleError(f"leaf must be exactly {LEAF_BYTES} bytes")
        if self._first_at is None:
            self._first_at = self._clock()
        self._leaves.append(leaf)
        if len(self._leaves) >= self.max_records:
            await self.flush()

    async def flush(self) -> int | None:
        """Anchor the pending batch; returns the on-chain batch id or None."""
        if not self._leaves:
            return None
        root = merkle_root(self._leaves)
        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            batch_id = (await self._chain.last_batch_id()) + 1
            try:
                await self._chain.submit(batch_id, root)
                await self._chain.verify_anchored(batch_id, root)
            except AnchorSubmissionError as exc:
                # The tx may have landed despite the error (timeout). Resolve
                # ambiguity on-chain before deciding to retry.
                if await self._resolved(batch_id, root):
                    return self._mark_anchored(batch_id, root, warn=True)
                last_error = exc
                await self._sleep(self._backoff(attempt))
                continue
            return self._mark_anchored(batch_id, root)
        raise AnchorSubmissionError(batch_id, root, self.max_attempts, str(last_error))

    async def run(self) -> None:
        """Idle loop: flush when the interval threshold elapses."""
        while not self._stopped:
            await self._flush_if_due()
            await self._sleep(1.0)

    def stop(self) -> None:
        self._stopped = True

    async def _flush_if_due(self) -> None:
        if self._first_at is None:
            return
        if self._clock() < self._first_at + self.interval_seconds:
            return
        try:
            await self.flush()
        except AnchorSubmissionError as exc:
            # Keep the buffer; wait a full interval before retrying so a
            # broken chain does not cause a tight retry loop.
            self._first_at = self._clock()
            logger.error("interval flush failed (buffer retained): %s", exc)

    async def _resolved(self, batch_id: int, root: bytes) -> bool:
        try:
            anchored = await self._chain.anchored_root(batch_id)
        except Exception:  # RPC may be down during the ambiguity window
            return False
        return anchored == root

    def _mark_anchored(self, batch_id: int, root: bytes, *, warn: bool = False) -> int:
        count = len(self._leaves)
        self._leaves.clear()
        self._first_at = None
        self._last_anchored_batch_id = batch_id
        (logger.warning if warn else logger.info)(
            "anchored batch %s (%s records) root=%s",
            batch_id,
            count,
            root.hex(),
        )
        return batch_id

    def _backoff(self, attempt: int) -> float:
        return min(self._backoff_base * (2 ** (attempt - 1)), 300.0)