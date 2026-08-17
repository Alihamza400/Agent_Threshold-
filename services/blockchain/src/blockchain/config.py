"""Chain registry + provider configuration.

A new chain is a config entry, not new code (5.1): the simulation, gas, and
oracle layers are chain-agnostic and keyed by ChainId.
"""

from __future__ import annotations

from at_shared.config import get_settings
from at_shared.schemas.tx import ChainId


class ChainConfig:
    """Static, per-chain configuration derived from Settings."""

    def __init__(
        self,
        chain_id: ChainId,
        rpc_urls: list[str],
        confirmations: int,
        eth_usd_aggregator: str = "",
    ) -> None:
        self.chain_id = chain_id
        self.rpc_urls = tuple(u for u in rpc_urls if u)
        self.confirmations = confirmations
        self.eth_usd_aggregator = eth_usd_aggregator

    @property
    def is_configured(self) -> bool:
        return bool(self.rpc_urls)


def load_chain_configs() -> dict[ChainId, ChainConfig]:
    """Build the chain registry from settings (fail-closed on unknown chain)."""
    s = get_settings()
    return {
        ChainId.ETHEREUM: ChainConfig(
            ChainId.ETHEREUM,
            [s.eth_rpc_url, s.eth_rpc_fallback_url],
            s.eth_confirmations,
            s.eth_usd_aggregator,
        ),
        ChainId.BASE: ChainConfig(
            ChainId.BASE,
            [s.base_rpc_url, s.base_rpc_fallback_url],
            s.base_confirmations,
        ),
        ChainId.ARBITRUM: ChainConfig(
            ChainId.ARBITRUM,
            [],
            s.base_confirmations,
        ),
    }


def chain_config(chain_id: ChainId) -> ChainConfig:
    return load_chain_configs()[chain_id]


def supported_chains() -> list[ChainId]:
    return [c for c in ChainId if chain_config(c).is_configured or c in (ChainId.BASE, ChainId.ETHEREUM)]