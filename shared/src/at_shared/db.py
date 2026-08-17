"""Database engine, session factory, and declarative base.

The connection pool is configured for the screening hot path: a bounded pool
with overflow for bursts, short connect/read timeouts, and fail-closed
behavior (pool_pre_ping prevents stale connections from hanging requests).
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Annotated

from sqlalchemy import String, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, mapped_column, sessionmaker

from at_shared.config import get_settings

settings = get_settings()

engine = create_engine(
    settings.database_url,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    pool_recycle=1800,
    connect_args={"connect_timeout": 5},
    echo=False,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)

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
    finally:
        db.close()


def init_db() -> None:
    """Import all models so they register on Base.metadata; create tables (dev)."""
    import at_shared.models  # noqa: F401

    Base.metadata.create_all(bind=engine)