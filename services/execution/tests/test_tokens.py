"""Decision token store tests: single-use, expiry, fail-closed."""

from __future__ import annotations

import time

import pytest
from at_shared.redis import redis_client
from execution_service.errors import TokenStoreError
from execution_service.tokens import DecisionTokenStore


def test_issue_and_consume_single_use() -> None:
    store = DecisionTokenStore(ttl_seconds=300)
    token = store.issue("tx-1")
    assert store.consume("tx-1", token) is True
    assert store.consume("tx-1", token) is False  # single-use


def test_wrong_token_rejected() -> None:
    store = DecisionTokenStore()
    store.issue("tx-1")
    assert store.consume("tx-1", "wrong-token") is False
    assert store.consume("tx-1", "") is False


def test_concurrent_consume_only_one_wins() -> None:
    store = DecisionTokenStore()
    token = store.issue("tx-1")
    results = [store.consume("tx-1", token) for _ in range(20)]
    assert results.count(True) == 1


def test_revoked_token_cannot_be_consumed() -> None:
    store = DecisionTokenStore()
    token = store.issue("tx-1")
    store.revoke("tx-1")
    assert store.consume("tx-1", token) is False


def test_token_expires() -> None:
    store = DecisionTokenStore(ttl_seconds=1)
    token = store.issue("tx-1")
    time.sleep(1.2)
    assert store.consume("tx-1", token) is False


def test_reissue_replaces_old_token() -> None:
    store = DecisionTokenStore()
    first = store.issue("tx-1")
    second = store.issue("tx-1")
    assert store.consume("tx-1", first) is False
    assert store.consume("tx-1", second) is True


def test_redis_down_fails_closed(monkeypatch) -> None:
    store = DecisionTokenStore()

    def boom(*args, **kwargs):
        import redis as _redis

        raise _redis.ConnectionError("down")

    monkeypatch.setattr(redis_client, "set", boom)
    with pytest.raises(TokenStoreError):
        store.issue("tx-1")

    monkeypatch.setattr(redis_client, "eval", boom)
    with pytest.raises(TokenStoreError):
        store.consume("tx-1", "token")
