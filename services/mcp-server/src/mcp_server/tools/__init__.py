"""MCP tool surface (all read-only, FR-MCP-02)."""

from __future__ import annotations

from mcp_server.registry import register_tool
from mcp_server.schemas import HistoryResult, PolicyRead, SimulateRequest, SimulationResult
from mcp_server.tools.history import get_agent_history
from mcp_server.tools.policy import get_policy
from mcp_server.tools.simulate import simulate_transaction

# Registration doubles as the allow-list gate: non-allow-listed or writable
# tools are refused at import time.
simulate_tool = register_tool("simulate_transaction", simulate_transaction, read_only=True)
policy_tool = register_tool("get_policy", get_policy, read_only=True)
history_tool = register_tool("get_agent_history", get_agent_history, read_only=True)

__all__ = [
    "simulate_tool",
    "policy_tool",
    "history_tool",
    "HistoryResult",
    "PolicyRead",
    "SimulateRequest",
    "SimulationResult",
]