"""Price oracle for cross-token USD normalization (5.7, FR-DATA-02).

Uses Chainlink AggregatorV3 (`latestRoundData`, `decimals`) via eth_call.
The ABI selectors are fixed constants and the reply words are decoded
directly, keeping the dependency surface minimal:

  latestRoundData()  -> 0xfeaf968c   (roundId, answer, startedAt, updatedAt, answeredInRound)
  decimals()         -> 0x313ce567   (uint8)

A StaticOracle fallback is used in development when no aggregator address is
configured; production must configure aggregators so spend limits evaluate in
a common USD unit. Oracle failures fail closed (OracleError).
"""

from __future__ import annotations

import abc

from blockchain.config import ChainConfig
from blockchain.errors import NoProviderConfiguredError, OracleError
from blockchain.rpc import RPCClient

_LATEST_ROUND_DATA_SELECTOR = "0xfeaf968c"
_DECIMALS_SELECTOR = "0x313ce567"
_WORD = 64  # two hex chars per byte * 32 bytes


class PriceOracle(abc.ABC):
    @abc.abstractmethod
    async def price_usd_per_native(self, chain: ChainConfig) -> float:
        """USD price of 1 native token (e.g. ETH/USD)."""

    @abc.abstractmethod
    async def usd_value(self, chain: ChainConfig, value_wei: int) -> float:
        """Convert a native value in wei to USD."""


class ChainlinkOracle(PriceOracle):
    """Reads the Chainlink aggregator for the chain's native token."""

    def __init__(self, client: RPCClient) -> None:
        self._client = client

    @staticmethod
    def _decode_int256_word(data: str, offset_words: int) -> int:
        # data starts with "0x" (2 chars), then 32-byte words
        start = 2 + offset_words * _WORD
        raw = data[start : start + _WORD]
        value = int(raw, 16)
        # int256 sign handling (Chainlink answers are positive; kept for safety)
        if value >= 1 << 255:
            value -= 1 << 256
        return value

    @staticmethod
    def _decode_uint8(data: str) -> int:
        return int(data[-2:], 16)

    async def price_usd_per_native(self, chain: ChainConfig) -> float:
        if not chain.eth_usd_aggregator:
            raise NoProviderConfiguredError("no aggregator configured for chain")
        tx = {"to": chain.eth_usd_aggregator, "data": _LATEST_ROUND_DATA_SELECTOR}
        data = await self._client.call_contract(tx)
        answer = self._decode_int256_word(data, 1)  # second word = answer
        if answer <= 0:
            raise OracleError(f"Chainlink returned non-positive price {answer}")

        decimals_tx = {"to": chain.eth_usd_aggregator, "data": _DECIMALS_SELECTOR}
        decimals = self._decode_uint8(await self._client.call_contract(decimals_tx))
        return answer / (10**decimals)

    async def usd_value(self, chain: ChainConfig, value_wei: int) -> float:
        price = await self.price_usd_per_native(chain)
        return value_wei * price / 10**18


class StaticOracle(PriceOracle):
    """Development fallback: a configured static price (never for production)."""

    def __init__(self, price_usd: float) -> None:
        self._price = price_usd

    async def price_usd_per_native(self, chain: ChainConfig) -> float:
        return self._price

    async def usd_value(self, chain: ChainConfig, value_wei: int) -> float:
        return value_wei * self._price / 10**18


def build_oracle(client: RPCClient, chain: ChainConfig, static_price: float | None = None) -> PriceOracle:
    """Pick the best available oracle; chainlink when configured, else static."""
    if chain.eth_usd_aggregator:
        return ChainlinkOracle(client)
    if static_price is not None:
        return StaticOracle(static_price)
    raise NoProviderConfiguredError(f"no oracle configured for {chain.chain_id.value}")