"""Pytest fixtures: isolated test DB + MCP server TestClient with signing."""

from __future__ import annotations

import os
import time

# Set env BEFORE any at_shared import: at_shared.db caches get_settings() at
# import time, so the test DB must already be selected or the app's SessionLocal
# binds to the dev database.
os.environ["APP_ENV"] = "test"
os.environ["POSTGRES_DB"] = "agentthreshold_test"

import pytest  # noqa: E402
from at_shared.api_keys import hash_api_key  # noqa: E402
from at_shared.models import Agent, ApiKey, Organization, Policy, User  # noqa: E402
from at_shared.security import hash_password  # noqa: E402
from at_shared.uuid7 import uuid7  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

TEST_DB_NAME = "agentthreshold_test"
ADMIN_EMAIL = "admin@agentthreshold.dev"
ADMIN_PASSWORD = "ChangeMe_Str0ng!"


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
    from at_shared.db import Base

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


def _session_factory(db_engine):
    return sessionmaker(bind=db_engine, expire_on_commit=False)


@pytest.fixture()
def db_session(db_engine):
    factory = _session_factory(db_engine)
    session = factory()
    yield session
    session.close()


@pytest.fixture()
def seed(db_session):
    """Bootstrap org + admin + one agent + key + policy, returns handles."""
    from sqlalchemy import select

    org = db_session.scalar(select(Organization).where(Organization.name == "AgentThreshold"))
    if org is None:
        org = Organization(id=uuid7(), name="AgentThreshold", tier="enterprise")
        db_session.add(org)
    admin = db_session.scalar(select(User).where(User.email == ADMIN_EMAIL))
    if admin is None:
        admin = User(
            id=uuid7(),
            org_id=org.id,
            email=ADMIN_EMAIL,
            role="admin",
            password_hash=hash_password(ADMIN_PASSWORD),
            is_active=True,
        )
        db_session.add(admin)

    agent = Agent(
        id=uuid7(),
        org_id=org.id,
        name="ai-hedge",
        wallet_address="0x" + uuid7()[-40:],
    )
    db_session.add(agent)

    raw_key = "at_" + uuid7()[-12:] + "k" * 28
    key = ApiKey(
        id=uuid7(),
        org_id=org.id,
        name="mcp-test",
        key_hash=hash_api_key(raw_key),
        key_prefix=raw_key[:12],
        agent_ids=[agent.id],
        is_active=True,
    )
    db_session.add(key)

    policy = Policy(
        id=uuid7(),
        agent_id=agent.id,
        version=1,
        spend_limit_usd=None,
        daily_spend_limit_usd=None,
        allow_list=[],
        deny_list=[],
        rate_limit_per_minute=None,
        gas_ceiling=3_000_000,
        anomaly_threshold=70.0,
        created_by=admin.id,
        is_active=True,
    )
    db_session.add(policy)
    db_session.commit()

    return {
        "org": org,
        "agent_id": agent.id,
        "raw_key": raw_key,
        "key_id": key.id,
        "policy": policy,
    }


@pytest.fixture()
def client(db_engine):
    from mcp.server.transport_security import TransportSecuritySettings
    from mcp_server.main import create_app

    app = create_app(
        json_response=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=["testserver", "localhost:*", "127.0.0.1:*"],
            allowed_origins=["http://testserver", "http://localhost:*"],
        ),
    )
    with TestClient(app) as c:
        yield c


def call_tool_headers(raw_key: str, body: bytes) -> dict[str, str]:
    """Build X-MCP-Timestamp / X-MCP-Signature headers (task 4.3)."""
    from mcp_server.auth import compute_signature

    ts = str(int(time.time()))
    sig = compute_signature(raw_key, ts, body)
    return {
        "X-API-Key": raw_key,
        "X-MCP-Timestamp": ts,
        "X-MCP-Signature": sig,
    }