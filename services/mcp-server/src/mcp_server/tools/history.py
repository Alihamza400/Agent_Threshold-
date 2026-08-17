"""`get_agent_history` MCP tool (read-only, FR-MCP-02).

Returns recent audited transactions for an agent, scoped to the API key.
"""

from __future__ import annotations

from at_shared.models import Agent, Transaction
from sqlalchemy import select

from mcp_server.auth import get_auth_context
from mcp_server.db import session_scope
from mcp_server.errors import MCPScopeError
from mcp_server.schemas import HistoryEntry, HistoryResult, validate_result


def get_agent_history(agent_id: str, limit: int = 20) -> HistoryResult:
    """Read the recent screening history for an agent (never mutates state)."""
    ctx = get_auth_context()
    ctx.authorize_agent(agent_id)

    bounded = max(1, min(limit, 100))

    with session_scope() as db:
        agent = db.scalar(select(Agent).where(Agent.id == agent_id))
        if agent is None or agent.org_id != ctx.org_id:
            raise MCPScopeError("agent not found for this key scope")

        rows = db.scalars(
            select(Transaction)
            .where(Transaction.agent_id == agent_id)
            .order_by(Transaction.created_at.desc())
            .limit(bounded)
        ).all()

        entries = [
            HistoryEntry(
                id=tx.id,
                chain_id=tx.chain_id,
                to_address=tx.to_address,
                value_wei=tx.value_wei,
                decision=tx.decision,
                risk_summary=tx.risk_summary,
                created_at=tx.created_at,
            )
            for tx in rows
        ]
    return validate_result(HistoryResult, HistoryResult(agent_id=agent_id, entries=entries))