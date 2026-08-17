"""`simulate_transaction` MCP tool (FR-MCP-01).

Delegates to the blockchain service's fork-per-request simulator (Phase 5);
the result is the frozen cross-chain SimulationResult contract. Fail-closed:
any backend failure surfaces as a structured `status="error"` result.
"""

from __future__ import annotations

from at_shared.models import Agent, Policy
from sqlalchemy import select

from mcp_server.auth import get_auth_context
from mcp_server.db import session_scope
from mcp_server.errors import MCPScopeError
from mcp_server.schemas import SimulateRequest, SimulationResult, validate_result


def _active_policy_gas_ceiling(db, agent_id: str) -> int | None:
    policy = db.scalar(
        select(Policy)
        .where(Policy.agent_id == agent_id, Policy.is_active.is_(True))
        .order_by(Policy.version.desc())
        .limit(1)
    )
    return policy.gas_ceiling if policy else None


async def simulate_transaction(req: SimulateRequest) -> SimulationResult:
    """Simulate against an isolated fork; read-only, never mutates state."""
    ctx = get_auth_context()
    ctx.authorize_agent(req.agent_id)

    with session_scope() as db:
        agent = db.scalar(select(Agent).where(Agent.id == req.agent_id))
        if agent is None or agent.org_id != ctx.org_id:
            raise MCPScopeError("agent not found for this key scope")
        gas_ceiling = _active_policy_gas_ceiling(db, req.agent_id)

    from blockchain.simulate import simulate_transaction as run_simulation

    result = await run_simulation(req, gas_ceiling=gas_ceiling)
    return validate_result(SimulationResult, result)