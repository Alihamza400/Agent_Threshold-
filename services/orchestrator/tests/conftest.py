"""Pytest fixtures: isolated test database for orchestrator tests."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("APP_ENV", "test")
# All service test conftests must use the SAME test DB name: at_shared.db binds
# engine/SessionLocal at import time, so a divergent DB name makes the binding
# order-dependent when the full monorepo suite runs (services would read/write
# different databases than the app they exercise).
os.environ.setdefault("POSTGRES_DB", "agentthreshold_test")

from at_shared.db import Base, get_db  # noqa: E402
from at_shared.models import Agent, ApiKey, Organization, Policy, Transaction  # noqa: E402
from at_shared.uuid7 import uuid7  # noqa: E402

TEST_DB_NAME = "agentthreshold_test"

WALLET = "0x" + "1" * 40
KNOWN_CP = "0x" + "2" * 40
NEW_CP = "0x" + "9" * 40


def _create_test_db() -> None:
    import at_shared.config as cfg

    s = cfg.get_settings()
    admin_url = (
        f"postgresql+psycopg://{s.postgres_user}:{s.postgres_password}"
        f"@{s.postgres_host}:{s.postgres_port}/postgres"
    )
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
    url = (
        f"postgresql+psycopg://{s.postgres_user}:{s.postgres_password}"
        f"@{s.postgres_host}:{s.postgres_port}/{TEST_DB_NAME}"
    )
    engine = create_engine(url)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def session_factory(db_engine):
    return sessionmaker(bind=db_engine, expire_on_commit=False)


@pytest.fixture()
def db_session(session_factory):
    session = session_factory()
    yield session
    session.close()


@pytest.fixture()
def org(db_session):
    org = Organization(id=uuid7(), name="orchestrator-test-org", tier="enterprise")
    db_session.add(org)
    db_session.commit()
    return org


@pytest.fixture()
def make_agent(db_session):
    def _make(org_id, *, name="agent", wallet=WALLET, halted=False):
        agent = Agent(
            id=uuid7(),
            org_id=org_id,
            name=name,
            wallet_address=wallet,
            halted=halted,
        )
        db_session.add(agent)
        db_session.commit()
        return agent

    return _make


@pytest.fixture()
def make_policy(db_session):
    def _make(agent_id, *, version=1, **kw):
        defaults = {
            "spend_limit_usd": 1000.0,
            "daily_spend_limit_usd": 5000.0,
            "anomaly_threshold": 70.0,
        }
        defaults.update(kw)
        policy = Policy(
            id=uuid7(),
            agent_id=agent_id,
            version=version,
            created_by="00000000-0000-0000-0000-000000000000",
            is_active=True,
            **defaults,
        )
        db_session.add(policy)
        db_session.commit()
        return policy

    return _make


@pytest.fixture()
def make_api_key(db_session):
    _counter = 0

    def _make(org_id, *, agent_ids=()):
        nonlocal _counter
        import uuid as _uuid

        from at_shared.api_keys import hash_api_key

        _counter += 1
        raw = f"at_orch_test_key_{_counter}_{_uuid.uuid4().hex[:16]}"
        key = ApiKey(
            id=uuid7(),
            org_id=org_id,
            name=f"orch-test-{_counter}",
            key_hash=hash_api_key(raw),
            key_prefix="at_orch_test",
            agent_ids=list(agent_ids),
            is_active=True,
        )
        db_session.add(key)
        db_session.commit()
        return raw, key

    return _make


def seed_known_transaction(db, org_id, agent_id, to_address, value_wei=10**16):
    """Seed a screened history row so the counterparty is 'known' (rule 9)."""
    from datetime import UTC, datetime

    tx = Transaction(
        id=uuid7(),
        agent_id=agent_id,
        org_id=org_id,
        chain_id="base",
        from_address=WALLET,
        to_address=to_address,
        value_wei=value_wei,
        usd_value=value_wei / 1e18,
        raw_params={},
        decision="approve",
        confidence=90.0,
        reasons=[],
        status="screened",
        created_at=datetime.now(UTC),
    )
    db.add(tx)
    db.commit()
    return tx


@pytest.fixture()
def client(db_engine, session_factory):
    def override_get_db():
        s = session_factory()
        try:
            yield s
        finally:
            s.close()

    from orchestrator.main import app

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
