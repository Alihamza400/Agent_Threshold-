"""Pytest fixtures for the execution adapter tests (DB + Redis).

Helpers are exposed as fixtures (not imported from sibling modules) so the
test directories stay non-package and the full monorepo suite has no module
basename collisions across services.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("POSTGRES_DB", "agentthreshold_test")

from at_shared.db import Base  # noqa: E402
from at_shared.models import Agent, Organization, Transaction  # noqa: E402
from at_shared.redis import redis_client  # noqa: E402
from at_shared.schemas.tx import ChainId  # noqa: E402
from at_shared.uuid7 import uuid7  # noqa: E402
from execution_service.validation import CHAIN_IDS  # noqa: E402

TEST_DB_NAME = "agentthreshold_test"

CHAIN = ChainId.BASE
EIP155 = CHAIN_IDS[CHAIN]


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
    """Isolate each test: wipe rows (schema recreated once per session)."""
    with db_engine.connect() as conn:
        conn.execute(text("TRUNCATE transactions, agents, organizations RESTART IDENTITY CASCADE"))
        conn.commit()
    yield


@pytest.fixture(autouse=True)
def _clean_redis():
    redis_client.flushdb()
    yield
    redis_client.flushdb()


@pytest.fixture()
def org_id(session_factory) -> str:
    with session_factory() as s:
        org = Organization(id=uuid7(), name="exec-org", tier="enterprise")
        s.add(org)
        s.commit()
        return org.id


# ------------------------------------------------------------------ helpers
@pytest.fixture()
def make_account():
    from eth_account import Account

    return Account.create


@pytest.fixture()
def seed_transaction(session_factory):
    def _seed(
        *,
        org_id: str,
        wallet: str,
        to_address: str | None = "0x" + "2" * 40,
        value_wei: int = 1000,
        calldata: str | None = "0x",
        gas_limit: int | None = 21000,
        gas_price_wei: int | None = 1_000_000_000,
        status: str = "approved",
        nonce: int | None = None,
    ) -> str:
        with session_factory() as s:
            agent = Agent(
                id=uuid7(),
                org_id=org_id,
                name="exec-agent",
                wallet_address=wallet,
            )
            s.add(agent)
            s.commit()
            agent_id = agent.id
            tx = Transaction(
                id=uuid7(),
                agent_id=agent_id,
                org_id=org_id,
                chain_id=CHAIN.value,
                from_address=wallet.lower(),
                to_address=to_address,
                value_wei=value_wei,
                raw_params={},
                calldata=calldata,
                gas_limit=gas_limit,
                gas_price_wei=gas_price_wei,
                decision="approve",
                status=status,
                nonce=nonce,
            )
            s.add(tx)
            s.commit()
            return tx.id

    return _seed


@pytest.fixture()
def sign_tx():
    def _sign(
        account,
        *,
        nonce: int,
        to: str,
        value: int = 1000,
        data: str = "0x",
        gas: int = 21000,
        gas_price: int = 1_000_000_000,
        chain_id: int = EIP155,
    ) -> str:
        signed = account.sign_transaction(
            {
                "chainId": chain_id,
                "nonce": nonce,
                "to": to,
                "value": value,
                "data": data,
                "gas": gas,
                "gasPrice": gas_price,
            }
        )
        return "0x" + signed.raw_transaction.hex()

    return _sign
