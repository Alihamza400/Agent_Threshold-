"""Pytest fixtures for the escalation notification service tests."""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("POSTGRES_DB", "agentthreshold_test")

from at_shared.db import Base  # noqa: E402
from at_shared.models import Organization  # noqa: E402
from at_shared.uuid7 import uuid7  # noqa: E402

from tests.helpers import seed_escalation  # noqa: E402

TEST_DB_NAME = "agentthreshold_test"


def _create_test_db() -> None:
    import at_shared.config as cfg

    s = cfg.get_settings()
    admin_url = f"postgresql+psycopg://{s.postgres_user}:{s.postgres_password}@{s.postgres_host}:{s.postgres_port}/postgres"
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": TEST_DB_NAME}
        ).scalar()
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{TEST_DB_NAME}"'))
    engine.dispose()


@pytest.fixture(scope="session")
def db_engine():
    _create_test_db()
    from at_shared.config import get_settings

    s = get_settings()
    url = f"postgresql+psycopg://{s.postgres_user}:{s.postgres_password}@{s.postgres_host}:{s.postgres_port}/{TEST_DB_NAME}"
    engine = create_engine(url)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def session_factory(db_engine):
    return sessionmaker(bind=db_engine, expire_on_commit=False)


@pytest.fixture(autouse=True)
def _clean_rows(db_engine):
    """Isolate each test: wipe rows (schema is recreated once per session).

    Safe within the monorepo run: every service's session-scoped `db_engine`
    drops and recreates the schema at its own session start, so rows from other
    suites are already gone and rows we leave are wiped by the next suite.
    """
    from sqlalchemy import text

    with db_engine.connect() as conn:
        conn.execute(
            text("TRUNCATE approvals, transactions, agents, organizations RESTART IDENTITY CASCADE")
        )
        conn.commit()
    yield


@pytest.fixture()
def org_id(session_factory) -> str:
    with session_factory() as s:
        org = Organization(id=uuid7(), name="Notif-Org", tier="enterprise")
        s.add(org)
        s.commit()
        return org.id


@pytest.fixture()
def escalation_id(session_factory, org_id) -> str:
    approval_id, _ = seed_escalation(session_factory, org_id=org_id)
    return approval_id
