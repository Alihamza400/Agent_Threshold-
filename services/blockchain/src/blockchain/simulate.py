"""Simulation orchestration — produces the frozen SimulationResult contract.

Fail-closed: any backend failure (missing anvil, RPC error, gas ceiling
exceeded) is surfaced as a structured `status="error"` result with a reason —
never a silent success.
"""

from __future__ import annotations

import shutil

from at_shared.config import get_settings
from at_shared.schemas.simulation import SimulateRequest, SimulationResult

from blockchain.config import ChainConfig
from blockchain.errors import BlockchainError
from blockchain.simulator import (
    AnvilProcessSimulator,
    LocalAnvilSimulator,
    Simulator,
    result_error,
)


def build_simulator(chain: ChainConfig) -> Simulator | None:
    """Pick a simulator backend in priority order; None when none available."""
    settings = get_settings()
    if settings.anvil_rpc_url:
        return LocalAnvilSimulator(chain, settings.anvil_rpc_url)
    if shutil.which("anvil"):
        return AnvilProcessSimulator(chain)
    return None


async def simulate_transaction(
    req: SimulateRequest,
    *,
    gas_ceiling: int | None = None,
    chain: ChainConfig | None = None,
    simulator: Simulator | None = None,
) -> SimulationResult:
    """Run a fork-per-request simulation and return the frozen result."""
    chain = chain or _chain_for(req)
    simulator = simulator or build_simulator(chain)
    if simulator is None:
        return result_error(
            req.chain_id,
            "simulation backend not available (no anvil / RPC configured)",
        )

    try:
        return await simulator.simulate(req, gas_ceiling=gas_ceiling)
    except BlockchainError as exc:
        return result_error(req.chain_id, str(exc))
    except Exception as exc:  # noqa: BLE001 - fail closed on any backend failure
        return result_error(req.chain_id, f"simulation failed: {exc}")


def _chain_for(req: SimulateRequest) -> ChainConfig:
    from blockchain.config import chain_config

    return chain_config(req.chain_id)