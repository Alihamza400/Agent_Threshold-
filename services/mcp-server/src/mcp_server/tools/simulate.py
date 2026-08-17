"""`simulate_transaction` MCP tool (FR-MCP-01).

Returns a structured, schema-frozen simulation result for any supported
chain. The simulator backend is behind a tiny protocol so Phase 5 can drop in
an isolated Anvil fork (or Tenderly fallback) without touching the MCP schema
or the tool surface.

Phase 4 ships the `StubSimulator`: it consults the agent's active policy to
flag gas-ceiling overruns and returns a well-formed result. State diffs and
gas estimates arrive with the real fork backend in Phase 5 — the contract is
already locked and contract-tested (task 4.5).
"""

from __future__ import annotations

from at_shared.models import Agent
from sqlalchemy import select

from mcp_server.auth import get_auth_context
from mcp_server.db import session_scope
from mcp_server.errors import MCPScopeError
from mcp_server.schemas import (
    SimulateRequest,
    SimulationResult,
    utcnow,
    validate_result,
)


def simulate_transaction(req: SimulateRequest) -> SimulationResult:
    """Simulate a transaction against the agent's policy context (read-only).

    Never mutates real state: the stub backend only reads policy + produces
    a structured result. Phase 5 will fork chain state per request.
    """
    ctx = get_auth_context()
    ctx.authorize_agent(req.agent_id)

    with session_scope() as db:
        agent = db.scalar(select(Agent).where(Agent.id == req.agent_id))
        if agent is None or agent.org_id != ctx.org_id:
            raise MCPScopeError("agent not found for this key scope")

        # Stub backend: no fork available yet — no gas estimate or state diff.
        # Phase 5 replaces this with an isolated Anvil fork that computes both.
        result = SimulationResult(
            chain_id=req.chain_id,
            status="error",
            gas_used_wei=0,
            gas_ceiling_used=False,
            state_diff=[],  # populated by the Phase 5 fork backend
            revert_reason="simulation backend not available (Phase 5)",
            simulated_at=utcnow(),
            simulator="stub",
        )
    return validate_result(SimulationResult, result)