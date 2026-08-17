"""DB access for MCP tools: short-lived, scoped sessions (fail-closed).

Each tool call opens its own session from the shared pool and closes it in a
`finally` — no cross-request state, no leaks. Reads only: the MCP server
never commits writes (FR-MCP-02).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from at_shared.db import SessionLocal
from sqlalchemy.orm import Session


@contextmanager
def session_scope() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()