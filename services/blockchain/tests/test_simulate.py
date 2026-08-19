"""Simulation orchestration + contract tests (5.2, 5.3; FR-CHAIN-01/02).

Uses the FakeSimulator so the suite needs no anvil; the contract + fail-closed
behavior are what matters here (real anvil is exercised in integration).
"""

from __future__ import annotations

import pytest
from at_shared.schemas.simulation import SimulateRequest, SimulationResult
from at_shared.schemas.tx import ChainId
from blockchain.config import ChainConfig
from blockchain.errors import GasExceedsCeilingError
from blockchain.simulate import simulate_transaction
from blockchain.simulator import FakeSimulator

AGENT = "01abc"
SELF = "0x1111111111111111111111111111111111111111"
TO = "0x2222222222222222222222222222222222222222"


def _req(**kw) -> SimulateRequest:
    base = dict(
        agent_id=AGENT,
        chain_id=ChainId.BASE,
        from_address=SELF,
        to_address=TO,
        value_wei=10**15,
        calldata=None,
    )
    base.update(kw)
    return SimulateRequest(**base)


@pytest.mark.asyncio
async def test_no_backend_fails_closed(monkeypatch):
    """No anvil/RPC backend available -> structured error, not a crash."""
    chain = ChainConfig(ChainId.BASE, [], confirmations=2)
    monkeypatch.setattr("blockchain.simulate.build_simulator", lambda chain: None)
    result = await simulate_transaction(_req(), chain=chain, simulator=None)
    assert result.status == "error"
    assert "backend" in result.revert_reason
    assert result.simulator == "stub"


@pytest.mark.asyncio
async def test_gas_ceiling_enforced_by_simulator():
    """FR-CHAIN-02: gas over ceiling is reported and flagged, not broadcast."""

    async def over_ceiling(req, *, gas_ceiling):
        from datetime import UTC, datetime

        return SimulationResult(
            chain_id=req.chain_id,
            status="error",
            gas_used_wei=300_000,
            gas_ceiling_used=True,
            revert_reason="estimated gas exceeds policy ceiling",
            simulated_at=datetime.now(UTC),
            simulator="anvil-fork",
        )

    chain = ChainConfig(ChainId.BASE, ["https://rpc.test"], 2)
    result = await simulate_transaction(
        _req(), chain=chain, simulator=FakeSimulator(result_factory=over_ceiling)
    )
    assert result.gas_ceiling_used is True
    assert result.status == "error"


@pytest.mark.asyncio
async def test_simulator_error_is_structured_not_raised():
    async def boom(req, *, gas_ceiling):
        raise GasExceedsCeilingError(999, 100)

    chain = ChainConfig(ChainId.BASE, ["https://rpc.test"], 2)
    result = await simulate_transaction(
        _req(), chain=chain, simulator=FakeSimulator(result_factory=boom)
    )
    assert result.status == "error"
    assert "ceiling" in result.revert_reason


@pytest.mark.asyncio
async def test_result_schema_is_frozen_contract():
    """The simulation result matches the frozen cross-chain contract."""
    chain = ChainConfig(ChainId.BASE, [], confirmations=2)
    result = await simulate_transaction(_req(), chain=chain, simulator=None)
    as_dict = result.model_dump()
    assert set(as_dict) == {
        "chain_id",
        "status",
        "gas_used_wei",
        "gas_ceiling_used",
        "state_diff",
        "revert_reason",
        "simulated_at",
        "simulator",
    }
    assert result.gas_used_wei >= 0
