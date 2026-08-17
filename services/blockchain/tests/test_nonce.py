"""Redis-locked nonce allocation tests (FR-CHAIN-03)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from blockchain.nonce import NonceAllocator

WALLET = "0x1111111111111111111111111111111111111111"


def test_sequential_reservations_unique():
    alloc = NonceAllocator(sync_nonce_getter=lambda _w: 10)
    seen = {alloc.reserve(WALLET) for _ in range(5)}
    assert seen == {10, 11, 12, 13, 14}


def test_concurrent_reservations_never_duplicate():
    """No two concurrent requests receive the same nonce (FR-CHAIN-03)."""
    alloc = NonceAllocator(sync_nonce_getter=lambda _w: 0)

    def grab(_i: int) -> int:
        return alloc.reserve(WALLET)

    with ThreadPoolExecutor(max_workers=16) as pool:
        nonces = list(pool.map(grab, range(64)))

    assert len(nonces) == 64
    assert len(set(nonces)) == 64, "duplicate nonce allocated under concurrency"
    assert min(nonces) == 0 and max(nonces) == 63


def test_seeding_uses_onchain_base():
    alloc = NonceAllocator(sync_nonce_getter=lambda _w: 100)
    assert alloc.reserve(WALLET) == 100
    assert alloc.reserve(WALLET) == 101


def test_reservations_recorded():
    alloc = NonceAllocator(sync_nonce_getter=lambda _w: 0)
    alloc.reserve(WALLET)
    alloc.reserve(WALLET)
    res = alloc.reservations(WALLET)
    assert set(res) == {"0", "1"}
    assert all(v == "reserved" for v in res.values())


def test_fresh_allocator_continues_counter():
    """The counter lives in Redis, so a new allocator continues the sequence."""
    NonceAllocator(sync_nonce_getter=lambda _w: 0).reserve(WALLET)
    assert NonceAllocator(sync_nonce_getter=lambda _w: 0).reserve(WALLET) == 1