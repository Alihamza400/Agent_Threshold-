"""Durable anchor worker: DB-backed batching + on-chain submission.

Phase 6 kept pending leaves in memory; a restart could drop unanchored
records. Phase 7 makes the buffer durable: the api-gateway writes immutable
`AuditRecord` rows to the shared database, and this worker periodically folds
unanchored records into a Merkle batch and anchors the root on-chain, then
marks the records with their `anchored_batch_id` in the same transaction.

Fail-closed contract (FR-AUDIT-01) is preserved via the in-memory
`AnchorBatcher` core (retries, ambiguity resolution, never-drop semantics):
on failure the records simply stay unanchored and the attempt is recorded in
`anchor_batches` (status `failed`) for observability; the next tick retries.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime

from at_shared.merkle import merkle_root
from at_shared.models import AnchorBatch, AuditRecord
from at_shared.uuid7 import uuid7
from sqlalchemy import select
from sqlalchemy.orm import Session

from audit_service.batcher import AnchorBatcher
from audit_service.errors import AnchorSubmissionError

logger = logging.getLogger("audit_service.worker")

Record = AuditRecord


class SqlAlchemyBatchStore:
    """Persistence half of the durable worker (sync; off the hot path)."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    def pending_count(self) -> int:
        with self._session_factory() as session:
            return len(session.scalars(select(Record.id).where(Record.anchored_batch_id.is_(None))).all())

    def load_pending(self, limit: int) -> list[Record]:
        with self._session_factory() as session:
            return list(
                session.scalars(
                    select(Record)
                    .where(Record.anchored_batch_id.is_(None))
                    .order_by(Record.created_at.asc(), Record.id.asc())
                    .limit(limit)
                ).all()
            )

    def upsert_batch(
        self,
        *,
        batch_id: int,
        root: str,
        record_count: int,
        status: str,
        submitted_at: datetime,
        anchored_at: datetime | None = None,
    ) -> None:
        with self._session_factory() as session:
            row = session.scalar(select(AnchorBatch).where(AnchorBatch.batch_id == batch_id))
            if row is None:
                row = AnchorBatch(
                    id=uuid7(),
                    batch_id=batch_id,
                    merkle_root=root,
                    record_count=record_count,
                    status=status,
                    submitted_at=submitted_at,
                    anchored_at=anchored_at,
                )
                session.add(row)
            else:
                row.merkle_root = root
                row.record_count = record_count
                row.status = status
                row.submitted_at = submitted_at
                row.anchored_at = anchored_at
            session.commit()

    def mark_anchored(self, record_ids: list[str], batch_id: int) -> None:
        with self._session_factory() as session:
            for rid in record_ids:
                record = session.get(Record, rid)
                if record is not None:
                    record.anchored_batch_id = batch_id
            session.commit()


class DbAnchorWorker:
    """Durable batching loop: DB -> Merkle tree -> on-chain anchor -> mark."""

    def __init__(
        self,
        *,
        store: SqlAlchemyBatchStore,
        chain: object,
        max_records: int = 1000,
        interval_seconds: float = 900.0,
        max_attempts: int = 5,
        backoff_base_seconds: float = 5.0,
        poll_seconds: float = 5.0,
        sleep: Callable[[float], asyncio.Future] = asyncio.sleep,
    ) -> None:
        self.store = store
        self._chain = chain
        self.max_records = max_records
        self.interval_seconds = interval_seconds
        self.max_attempts = max_attempts
        self._backoff_base = backoff_base_seconds
        self._poll = poll_seconds
        self._sleep = sleep
        self._first_pending_at: float | None = None
        self._last_anchored_batch_id: int | None = None
        self._stopped = False

    @property
    def pending_count(self) -> int:
        return self.store.pending_count()

    @property
    def last_anchored_batch_id(self) -> int | None:
        return self._last_anchored_batch_id

    def stop(self) -> None:
        self._stopped = True

    async def run(self) -> None:
        while not self._stopped:
            try:
                await self.tick()
            except Exception:  # noqa: BLE001 - the loop must survive transient faults
                logger.exception("worker tick failed")
            await self._sleep(self._poll)

    async def tick(self) -> None:
        pending = self.store.load_pending(self.max_records)
        if not pending:
            self._first_pending_at = None
            return

        now = time.monotonic()
        if self._first_pending_at is None:
            self._first_pending_at = now
        count_due = len(pending) >= self.max_records
        interval_due = now - self._first_pending_at >= self.interval_seconds
        if not count_due and not interval_due:
            return

        submitted_at = datetime.now(UTC)
        leaves = [bytes.fromhex(r.event_hash) for r in pending]
        root = merkle_root(leaves)
        record_ids = [r.id for r in pending]

        batcher = AnchorBatcher(
            chain=self._chain,
            max_records=self.max_records,
            interval_seconds=self.interval_seconds,
            max_attempts=self.max_attempts,
            backoff_base_seconds=self._backoff_base,
        )
        try:
            for leaf in leaves:
                await batcher.add(leaf)
            await batcher.flush()
        except AnchorSubmissionError as exc:
            # Failed attempts are recorded for observability; the records stay
            # unanchored and are retried on the next interval (never dropped).
            self.store.upsert_batch(
                batch_id=exc.batch_id,
                root=exc.root.hex(),
                record_count=len(record_ids),
                status="failed",
                submitted_at=submitted_at,
            )
            self._first_pending_at = now
            logger.error("anchor failed (records retained): %s", exc)
            return

        batch_id = batcher.last_anchored_batch_id
        self.store.upsert_batch(
            batch_id=batch_id,
            root=root.hex(),
            record_count=len(record_ids),
            status="anchored",
            submitted_at=submitted_at,
            anchored_at=datetime.now(UTC),
        )
        self.store.mark_anchored(record_ids, batch_id)
        self._last_anchored_batch_id = batch_id
        self._first_pending_at = None
        logger.info("anchored batch %s (%s records) root=%s", batch_id, len(record_ids), root.hex())