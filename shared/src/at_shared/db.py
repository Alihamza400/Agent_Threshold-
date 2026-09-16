"""Database engine, session factory, and declarative base.

The connection pool is configured for the screening hot path: a bounded pool
with overflow for bursts, short connect/read timeouts, and fail-closed
behavior (pool_pre_ping prevents stale connections from hanging requests).

Binding is LAZY (first use, not import): the engine/session factory resolve
``get_settings()`` when first needed, so a service's effective database URL is
pinned from the environment at request time rather than at process import.
This keeps the monorepo test suite order-independent — every service's test
conftest pins ``POSTGRES_DB`` before any test executes, regardless of which
module happens to import this package first during collection.
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Annotated

from sqlalchemy import String, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, mapped_column, sessionmaker

from at_shared.config import get_settings

_engine: Engine | None = None
_sessionmaker: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    """Create (once) and return the shared engine."""
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_engine(
            settings.database_url,
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,
            pool_recycle=1800,
            connect_args={"connect_timeout": 5},
            echo=False,
        )
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    """Create (once) and return the shared session factory."""
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = sessionmaker(
            bind=get_engine(),
            autoflush=False,
            expire_on_commit=False,
            class_=Session,
        )
    return _sessionmaker


class _LazyEngine:
    """Module-level `engine` facade resolving on first use (import-compatible).

    Keeps ``from at_shared.db import engine`` working without pinning the DB
    URL at import time.
    """

    def connect(self, *args, **kwargs):
        return get_engine().connect(*args, **kwargs)

    def __getattr__(self, name: str):
        return getattr(get_engine(), name)


engine = _LazyEngine()


def SessionLocal() -> Session:  # noqa: N802 - legacy name kept for import compat
    """Request-scoped session factory (callable, import-compatible)."""
    return get_session_factory()()


# UUIDv7 primary key type
UUID7 = Annotated[
    str,
    mapped_column(String(36), primary_key=True, default=None),  # value set in model base
]


class Base(DeclarativeBase):
    """Declarative base with common column conventions."""


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a request-scoped session."""
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db() -> None:
    """Import all models so they register on Base.metadata; create tables (dev)."""
    import at_shared.models  # noqa: F401

    Base.metadata.create_all(bind=get_engine())
