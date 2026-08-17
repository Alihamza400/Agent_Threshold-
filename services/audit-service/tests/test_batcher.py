"""AnchorBatcher tests: thresholds, fail-closed retention, retries, idempotency."""

import asyncio

import pytest
from audit_service.batcher import AnchorBatcher
from audit_service.errors import (
    AnchorRevertedError,
    AnchorSubmissionError,
    AnchorVerificationError,
    MerkleError,
)
from audit_service.merkle import leaf_hash, merkle_root

ZERO = b"\x00" * 32


class FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


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
        if self.mode == "ambiguous":
            self.roots[batch_id] = root  # tx landed, but the client errored
            self.last = batch_id
            raise AnchorSubmissionError(batch_id, root, 1, "confirm timeout")
        if self.mode == "bad_root":
            self.roots[batch_id] = ZERO  # chain stored a wrong root
            self.last = batch_id
            return "0xdead"
        if self.mode == "revert":
            raise AnchorRevertedError(batch_id, root, 1, "reverted")
        self.roots[batch_id] = root
        self.last = batch_id
        return "0xdead"

    async def verify_anchored(self, batch_id: int, root: bytes) -> None:
        if self.roots.get(batch_id) != root:
            raise AnchorVerificationError(batch_id, root, 1, "root mismatch")

    async def anchored_root(self, batch_id: int) -> bytes:
        return self.roots.get(batch_id, ZERO)


def make_batcher(chain, *, clock: FakeClock | None = None, **kw):
    kw.setdefault("max_records", 1000)
    kw.setdefault("interval_seconds", 900.0)
    kw.setdefault("max_attempts", 3)
    kw.setdefault("backoff_base_seconds", 0.001)
    kw.setdefault("sleep", asyncio.sleep)
    return AnchorBatcher(chain=chain, clock=clock or FakeClock(), **kw)


@pytest.mark.asyncio
async def test_count_threshold_triggers_flush():
    chain = FakeChain()
    batcher = make_batcher(chain, max_records=3)
    leaves = [leaf_hash(f"r{i}".encode()) for i in range(3)]
    for leaf in leaves:
        await batcher.add(leaf)
    assert batcher.last_anchored_batch_id == 1
    assert batcher.pending_count == 0
    assert chain.roots[1] == merkle_root(leaves)


@pytest.mark.asyncio
async def test_interval_threshold_triggers_flush():
    chain = FakeChain()
    clock = FakeClock()
    batcher = make_batcher(chain, clock=clock)
    await batcher.add(leaf_hash(b"a"))
    assert batcher.pending_count == 1

    clock.advance(899)
    await batcher._flush_if_due()
    assert batcher.pending_count == 1  # not due yet

    clock.advance(1)
    await batcher._flush_if_due()
    assert batcher.pending_count == 0
    assert batcher.last_anchored_batch_id == 1


@pytest.mark.asyncio
async def test_batch_ids_are_strictly_increasing():
    chain = FakeChain()
    batcher = make_batcher(chain, max_records=2)
    for i in range(5):
        await batcher.add(leaf_hash(f"r{i}".encode()))
    assert batcher.last_anchored_batch_id == 2
    assert [id for id, _ in chain.submits] == [1, 2]
    assert batcher.pending_count == 1


@pytest.mark.asyncio
async def test_failure_retains_buffer_and_raises_after_attempts():
    chain = FakeChain(mode="down")
    batcher = make_batcher(chain)
    await batcher.add(leaf_hash(b"a"))
    with pytest.raises(AnchorSubmissionError):
        await batcher.flush()
    assert batcher.pending_count == 1  # never dropped


@pytest.mark.asyncio
async def test_ambiguous_failure_resolves_on_chain():
    chain = FakeChain(mode="ambiguous")
    batcher = make_batcher(chain)
    await batcher.add(leaf_hash(b"a"))
    batch_id = await batcher.flush()
    assert batch_id == 1
    assert batcher.pending_count == 0
    assert batcher.last_anchored_batch_id == 1


@pytest.mark.asyncio
async def test_wrong_root_on_chain_keeps_buffer():
    chain = FakeChain(mode="bad_root")
    batcher = make_batcher(chain)
    await batcher.add(leaf_hash(b"a"))
    with pytest.raises(AnchorSubmissionError):
        await batcher.flush()
    assert batcher.pending_count == 1
    assert batcher.last_anchored_batch_id is None


@pytest.mark.asyncio
async def test_revert_keeps_buffer():
    chain = FakeChain(mode="revert")
    batcher = make_batcher(chain)
    await batcher.add(leaf_hash(b"a"))
    with pytest.raises(AnchorSubmissionError):
        await batcher.flush()
    assert batcher.pending_count == 1


@pytest.mark.asyncio
async def test_flush_noop_when_empty():
    chain = FakeChain()
    batcher = make_batcher(chain)
    assert await batcher.flush() is None
    assert chain.submits == []


@pytest.mark.asyncio
async def test_invalid_leaf_length_rejected():
    chain = FakeChain()
    batcher = make_batcher(chain)
    with pytest.raises(MerkleError):
        await batcher.add(b"short")
    assert batcher.pending_count == 0


@pytest.mark.asyncio
async def test_run_loop_stops_and_flushes_on_interval():
    chain = FakeChain()
    clock = FakeClock()
    batcher = make_batcher(chain, clock=clock)
    await batcher.add(leaf_hash(b"a"))

    async def fake_sleep(_seconds: float) -> None:
        clock.advance(900)
        await asyncio.sleep(0)  # yield so the main coroutine can stop()

    batcher._sleep = fake_sleep
    run_task = asyncio.create_task(batcher.run())
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    batcher.stop()
    await run_task
    assert batcher.last_anchored_batch_id == 1
    assert batcher.pending_count == 0