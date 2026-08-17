"""Errors for the MCP server.

Every failure surfaces as a structured MCP tool/request error. Callers
(screening agents / SDK) treat any error as a rejection — never a silent
success (fail-closed, TRD 4.9).
"""

from __future__ import annotations


class MCPError(Exception):
    """Base class for all MCP server errors."""

    def __init__(self, message: str, *, code: int = -32000) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


class MCPAuthError(MCPError):
    """Missing / invalid API key, expired or invalid HMAC signature."""

    def __init__(self, message: str = "Unauthorized") -> None:
        super().__init__(message, code=-32001)


class MCPScopeError(MCPError):
    """Authenticated principal is not allowed to touch the target resource."""

    def __init__(self, message: str = "Resource not in API key scope") -> None:
        super().__init__(message, code=-32003)


class MCPToolNotAllowedError(MCPError):
    """Tool not in the allow-list or not a read-only tool (FR-MCP-02)."""

    def __init__(self, tool: str) -> None:
        super().__init__(f"Tool '{tool}' is not allow-listed", code=-32601)


class MCPSchemaError(MCPError):
    """Tool result failed response-schema validation (task 4.4)."""

    def __init__(self, message: str = "Malformed tool result") -> None:
        super().__init__(message, code=-32002)