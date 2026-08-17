"""DbAnchorWorker tests: durable DB-backed batching, anchoring, failure retention."""

from __future__ import annotations

import asyncio

import pytest
from at_shared.db import Base
from at_shared.merkle import merkle_root
from at_shared.models import AnchorBatch, AuditRecord
from at_shared.uuid7 import uuid7
from audit_service.errors import AnchorSubmissionError
from audit_service.merkle import leaf_hash
from audit_service.worker import DbAnchorWorker, SqlAlchemyBatchStore
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ZERO = b"\x00" * 32

pytestmark = pytest.mark.asyncio

ORG_ID = "org-test-00000000000000000000000000000000"
AGENT_ID = "agent-test-0000000000000000000000000000000"


class FakeChain:
    def __init__(self, *, mode: str = "ok") -> None:
        self.last = 0
        self.roots: dict[int, bytes] = {}
        self.submits: list[tuple[int, bytes]] = []
        self.mode = mode

    async def last_batch_id(self) -> int:
        return self.last

    async def submit(self, batch_id: int, root: bytes) -> str:
        self.submits.append((batch_id, root))
        if self.mode == "down":
            raise AnchorSubmissionError(batch_id, root, 1, "rpc unreachable")
        self.roots[batch_id] = root
        self.last = batch_id
        return "0xdead"

    async def verify_anchored(self, batch_id: int, root: bytes) -> None:
        if self.roots.get(batch_id) != root:
            raise AnchorSubmissionError(batch_id, root, 1, "root mismatch")

    async def anchored_root(self, batch_id: int) -> bytes:
        return self.roots.get(batch_id, ZERO)


@pytest.fixture()
def engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return engine


@pytest.fixture()
def factory(engine):
    return sessionmaker(bind=engine, expire_on_commit=False)


def _insert_record(factory, *, event_hash, anchored=None):
    with factory() as s:
        rec = AuditRecord(
            id=uuid7(),
            org_id=ORG_ID,
            agent_id=AGENT_ID,
            transaction_id=None,
            event_type="decision",
            event_hash=event_hash.hex(),
            details={"decision": "approve"},
            anchored_batch_id=anchored,
        )
        s.add(rec)
        s.commit()
        return rec.id


def make_worker(factory, chain, **kw):
    kw.setdefault("max_records", 1000)
    kw.setdefault("interval_seconds", 900.0)
    kw.setdefault("max_attempts", 3)
    kw.setdefault("backoff_base_seconds", 0.001)
    kw.setdefault("poll_seconds", 0.01)
    return DbAnchorWorker(store=SqlAlchemyBatchStore(factory), chain=chain, **kw)


async def test_tick_noop_when_no_pending(factory):
    chain = FakeChain()
    worker = make_worker(factory, chain)
    await worker.tick()
    assert chain.submits == []


async def test_tick_waits_for_interval_and_count(factory):
    chain = FakeChain()
    worker = make_worker(factory, chain)
    _insert_record(factory, event_hash=leaf_hash(b"a"))
    await worker.tick()  # neither count nor interval threshold met yet
    assert chain.submits == []
    assert worker.pending_count == 1


async def test_count_threshold_anchors_and_marks(factory):
    chain = FakeChain()
    worker = make_worker(factory, chain, max_records=2)
    ids = [
        _insert_record(factory, event_hash=leaf_hash(f"r{i}".encode())) for i in range(2)
    ]
    await worker.tick()
    assert chain.submits == [(1, merkle_root([leaf_hash(b"r0"), leaf_hash(b"r1")]))]
    assert worker.last_anchored_batch_id == 1
    assert worker.pending_count == 0

    with factory() as s:
        for rid in ids:
            assert s.get(AuditRecord, rid).anchored_batch_id == 1
        batch = s.scalar(select(AnchorBatch).where(AnchorBatch.batch_id == 1))
        assert batch.status == "anchored"
        assert batch.record_count == 2


async def test_interval_threshold_anchors(factory):
    chain = FakeChain()
    worker = make_worker(factory, chain)
    _insert_record(factory, event_hash=leaf_hash(b"x"))
    worker._first_pending_at = -1000.0  # interval long since elapsed
    await worker.tick()
    assert worker.last_anchored_batch_id == 1
    assert worker.pending_count == 0


async def test_chain_failure_retains_records_and_records_failed_batch(factory):
    chain = FakeChain(mode="down")
    worker = make_worker(factory, chain, max_records=1)
    _insert_record(factory, event_hash=leaf_hash(b"r"))
    await worker.tick()
    assert worker.pending_count == 1  # never dropped
    assert worker.last_anchored_batch_id is None

    with factory() as s:
        batch = s.scalar(select(AnchorBatch).where(AnchorBatch.batch_id == 1))
        assert batch is not None
        assert batch.status == "failed"


async def test_retries_on_next_tick_after_failure(factory):
    chain = FakeChain(mode="down")
    worker = make_worker(factory, chain, max_records=1)
    _insert_record(factory, event_hash=leaf_hash(b"r"))
    await worker.tick()
    assert worker.pending_count == 1

    chain.mode = "ok"
    worker._first_pending_at = -1000.0
    await worker.tick()
    assert worker.last_anchored_batch_id == 1
    assert worker.pending_count == 0


async def test_only_unanchored_records_are_batched(factory):
    chain = FakeChain()
    worker = make_worker(factory, chain, max_records=1)
    already = _insert_record(factory, event_hash=leaf_hash(b"a"), anchored=7)
    pending = _insert_record(factory, event_hash=leaf_hash(b"b"))
    await worker.tick()
    with factory() as s:
        assert s.get(AuditRecord, already).anchored_batch_id == 7
        assert s.get(AuditRecord, pending).anchored_batch_id == 1


@pytest.mark.asyncio
async def test_run_loop_anchors_on_interval(engine, factory):
    chain = FakeChain()
    worker = make_worker(factory, chain)
    _insert_record(factory, event_hash=leaf_hash(b"z"))
    worker._first_pending_at = -1000.0

    async def fake_sleep(_: float) -> None:
        await asyncio.sleep(0)
        worker.stop()

    worker._sleep = fake_sleep
    run_task = asyncio.create_task(worker.run())
    await asyncio.sleep(0)
    await run_task
    assert worker.last_anchored_batch_id == 1
    assert worker.pending_count == 0