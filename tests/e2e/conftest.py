"""Phase 8.7 end-to-end fixtures (real Postgres + Redis + real HTTP gateway).

The E2E scenario drives the full chain over REAL HTTP for the SDK hop,
mirroring the deployed topology:

    Python SDK (HTTP) -> API Gateway -> in-process orchestrator pipeline
    -> escalation Approval (DB) -> notification outbox delivery
    -> approver (HTTP, JWT) -> Execution Adapter (token + nonce + broadcast)

All service packages are uv workspace members, so the root test env imports
them in-process exactly as the services are wired today (the gateway imports
the orchestrator `Pipeline` directly; execution + notification read the shared
DB). The gateway is served by a real uvicorn instance on an ephemeral port so
the SDK's HTTP client exercises a true network hop.
"""

from __future__ import annotations

import os
import socket
import threading
from dataclasses import dataclass

import httpx
import pytest
import uvicorn
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("POSTGRES_DB", "agentthreshold_test")

from at_shared.db import Base, get_db  # noqa: E402
from at_shared.models import Organization, User  # noqa: E402
from at_shared.security import hash_password  # noqa: E402
from at_shared.uuid7 import uuid7  # noqa: E402

TEST_DB_NAME = "agentthreshold_test"
ORG_NAME = "E2E Org"
ADMIN_EMAIL = "e2e-admin@agentthreshold.dev"
ADMIN_PASSWORD = "E2eAdmin_Str0ng!"
APPROVER_EMAIL = "e2e-approver@agentthreshold.dev"
APPROVER_PASSWORD = "E2eApprover_Str0ng!"


@dataclass
class GatewayEnv:
    """Everything the E2E needs to drive every hop of the chain."""

    app: object
    base_url: str
    client: httpx.Client
    session_factory: sessionmaker
    org_id: str
    admin_token: str
    approver_token: str


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
def _flush_redis():
    from at_shared.redis import redis_client

    redis_client.flushdb()
    yield
    redis_client.flushdb()


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_server(app, port: int) -> threading.Thread:
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):  # wait until the socket is accepting connections
        if server.started:
            return thread
        import time

        time.sleep(0.05)
    raise RuntimeError("e2e gateway server failed to start")


@pytest.fixture()
def gateway(db_engine):
    """Boot the gateway over real HTTP with the in-process orchestrator
    pipeline and seeded org + admin/approver users against the test DB."""
    from app.main import app
    from orchestrator.pipeline import Pipeline

    factory = sessionmaker(bind=db_engine, expire_on_commit=False)

    def override_get_db():
        s = factory()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override_get_db
    from app.routers import transactions as tx_router

    tx_router._pipeline = Pipeline(session_factory=factory, simulation_mode="disabled")

    with factory() as s:
        org = s.query(Organization).filter_by(name=ORG_NAME).first()
        if org is None:
            org = Organization(id=uuid7(), name=ORG_NAME, tier="enterprise")
            s.add(org)
            s.commit()
        admin = s.query(User).filter_by(email=ADMIN_EMAIL).first()
        if admin is None:
            admin = User(
                id=uuid7(),
                org_id=org.id,
                email=ADMIN_EMAIL,
                role="admin",
                password_hash=hash_password(ADMIN_PASSWORD),
                is_active=True,
            )
            s.add(admin)
            s.commit()
        approver = s.query(User).filter_by(email=APPROVER_EMAIL).first()
        if approver is None:
            approver = User(
                id=uuid7(),
                org_id=org.id,
                email=APPROVER_EMAIL,
                role="approver",
                password_hash=hash_password(APPROVER_PASSWORD),
                is_active=True,
            )
            s.add(approver)
            s.commit()
        org_id = org.id

    port = _free_port()
    _start_server(app, port)
    base_url = f"http://127.0.0.1:{port}"

    with httpx.Client(base_url=base_url) as client:
        admin_token = client.post(
            "/v1/auth/login",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        ).json()["access_token"]
        approver_token = client.post(
            "/v1/auth/login",
            json={"email": APPROVER_EMAIL, "password": APPROVER_PASSWORD},
        ).json()["access_token"]
        yield GatewayEnv(
            app=app,
            base_url=base_url,
            client=client,
            session_factory=factory,
            org_id=org_id,
            admin_token=admin_token,
            approver_token=approver_token,
        )

    app.dependency_overrides.clear()


@pytest.fixture()
def account():
    from eth_account import Account

    return Account.create()
