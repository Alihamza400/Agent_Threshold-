"""Pytest fixtures: isolated test database + FastAPI TestClient."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("POSTGRES_DB", "agentthreshold_test")

from at_shared.db import Base, get_db  # noqa: E402
from at_shared.models import Organization, User  # noqa: E402
from at_shared.security import hash_password  # noqa: E402
from at_shared.uuid7 import uuid7  # noqa: E402

TEST_DB_NAME = "agentthreshold_test"
ADMIN_EMAIL = "admin@agentthreshold.dev"
ADMIN_PASSWORD = "ChangeMe_Str0ng!"


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


def test_session_factory(db_engine):
    return sessionmaker(bind=db_engine, expire_on_commit=False)


@pytest.fixture()
def db_session(db_engine):
    factory = test_session_factory(db_engine)
    session = factory()
    yield session
    session.close()


@pytest.fixture()
def client(db_engine):
    factory = test_session_factory(db_engine)

    def override_get_db():
        s = factory()
        try:
            yield s
        finally:
            s.close()

    from app.main import app

    app.dependency_overrides[get_db] = override_get_db

    # Bootstrap org + admin
    with factory() as s:
        org = s.query(Organization).filter_by(name="AgentThreshold").first()
        if org is None:
            org = Organization(id=uuid7(), name="AgentThreshold", tier="enterprise")
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

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()


@pytest.fixture()
def admin_token(client) -> str:
    resp = client.post(
        "/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]