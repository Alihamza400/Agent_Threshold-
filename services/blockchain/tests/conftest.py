"""Test fixtures: chain configs + Redis-backed nonce allocator (test DB)."""

from __future__ import annotations

import os

# Bind to the test DB BEFORE any at_shared import (settings are cached).
os.environ["APP_ENV"] = "test"
os.environ["POSTGRES_DB"] = "agentthreshold_test"

import pytest  # noqa: E402
from at_shared.redis import redis_client  # noqa: E402
from at_shared.schemas.tx import ChainId  # noqa: E402
from blockchain.config import ChainConfig  # noqa: E402

PRIMARY = "https://rpc.primary.test"
FALLBACK = "https://rpc.fallback.test"


@pytest.fixture()
def chain() -> ChainConfig:
    return ChainConfig(ChainId.BASE, [PRIMARY, FALLBACK], confirmations=2)


@pytest.fixture()
def chain_single() -> ChainConfig:
    return ChainConfig(ChainId.BASE, [PRIMARY], confirmations=2)


@pytest.fixture(autouse=True)
def _clean_redis():
    redis_client.flushdb()
    yield
    redis_client.flushdb()