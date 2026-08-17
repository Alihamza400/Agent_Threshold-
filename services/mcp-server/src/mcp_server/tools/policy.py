"""`get_policy` MCP tool (read-only, FR-MCP-02).

Returns the active policy snapshot for an agent, scoped to the API key.
"""

from __future__ import annotations

from at_shared.models import Agent, Policy
from sqlalchemy import select

from mcp_server.auth import get_auth_context
from mcp_server.db import session_scope
from mcp_server.errors import MCPScopeError
from mcp_server.schemas import PolicyRead, validate_result


def get_policy(agent_id: str) -> PolicyRead:
    """Read the active policy for an agent (never mutates state)."""
    ctx = get_auth_context()
    ctx.authorize_agent(agent_id)

    with session_scope() as db:
        agent = db.scalar(select(Agent).where(Agent.id == agent_id))
        if agent is None or agent.org_id != ctx.org_id:
            raise MCPScopeError("agent not found for this key scope")

        policy = db.scalar(
            select(Policy)
            .where(Policy.agent_id == agent_id, Policy.is_active.is_(True))
            .order_by(Policy.version.desc())
            .limit(1)
        )
        if policy is None:
            raise MCPScopeError("no active policy for agent")

        result = PolicyRead(
            agent_id=policy.agent_id,
            version=policy.version,
            spend_limit_usd=policy.spend_limit_usd,
            daily_spend_limit_usd=policy.daily_spend_limit_usd,
            allow_list=list(policy.allow_list or []),
            deny_list=list(policy.deny_list or []),
            rate_limit_per_minute=policy.rate_limit_per_minute,
            gas_ceiling=policy.gas_ceiling,
            anomaly_threshold=policy.anomaly_threshold,
            active_from_minute=policy.active_from_minute,
            active_to_minute=policy.active_to_minute,
            is_active=policy.is_active,
        )
    return validate_result(PolicyRead, result)