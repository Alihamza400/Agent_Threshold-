"""Tool registry + allow-listing (task 4.3, FR-MCP-02).

The server layer decides what tools exist and what each may do:

- Only tools in the allow-list are registered / callable.
- No mutating tools are registered; any attempt to add one is rejected at
  registration time (defense in depth: even a bug in a handler cannot write).
- Every tool declares a response schema; every result is validated against it
  before it is returned (task 4.4) — malformed output is a failure.
"""

from __future__ import annotations

from collections.abc import Callable

from mcp_server.auth import _MUTATING_TOOLS
from mcp_server.errors import MCPToolNotAllowedError
from mcp_server.schemas import validate_result

# Default allow-list exposed to authenticated MCP clients (FR-MCP-02).
ALLOWED_TOOLS: frozenset[str] = frozenset(
    {"simulate_transaction", "get_policy", "get_agent_history"}
)


def assert_tool_allowed(tool_name: str) -> None:
    """Reject any tool not in the allow-list at call time (fail-closed)."""
    if tool_name not in ALLOWED_TOOLS:
        raise MCPToolNotAllowedError(tool_name)


def register_tool(
    name: str,
    handler: Callable,
    *,
    read_only: bool,
) -> Callable:
    """Register a tool handler, enforcing the read-only invariant.

    `_MUTATING_TOOLS` is intentionally empty; any tool that marks itself
    writable is refused at registration (FR-MCP-02).
    """
    if name not in ALLOWED_TOOLS:
        raise MCPToolNotAllowedError(name)
    if not read_only or name in _MUTATING_TOOLS:
        raise MCPToolNotAllowedError(f"tool '{name}' is not read-only")
    return handler


def validated(
    schema,
    result,
):
    """Validate a tool result against its schema (task 4.4)."""
    return validate_result(schema, result)