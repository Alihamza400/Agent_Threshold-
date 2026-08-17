"""Agent registration tests (Phase 1 walking skeleton acceptance)."""

from __future__ import annotations

from at_shared.models import Agent, Policy

WALLET = "0xabcdef1234567890abcdef1234567890abcdef12"


def test_register_agent(client, admin_token):
    resp = client.post(
        "/v1/agents/register",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"name": "agent-alpha", "wallet_address": WALLET},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["agent"]["wallet_address"] == WALLET
    assert body["agent"]["status"] == "active"
    assert body["agent"]["halted"] is False
    assert body["default_policy_id"]


def test_register_duplicate_wallet_conflict(client, admin_token):
    for _ in range(2):
        resp = client.post(
            "/v1/agents/register",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"name": "agent-alpha", "wallet_address": WALLET},
        )
    assert resp.status_code == 409


def test_register_invalid_wallet(client, admin_token):
    resp = client.post(
        "/v1/agents/register",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"name": "bad-wallet", "wallet_address": "0x123"},
    )
    assert resp.status_code == 422


def test_default_policy_persisted(client, admin_token, db_session):
    client.post(
        "/v1/agents/register",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"name": "agent-beta", "wallet_address": WALLET},
    )
    agent = db_session.query(Agent).filter_by(wallet_address=WALLET).one()
    policy = db_session.query(Policy).filter_by(agent_id=agent.id, is_active=True).one()
    assert policy.version == 1
    assert policy.spend_limit_usd == 100.0
    assert policy.rate_limit_per_minute == 30


def test_get_agent(client, admin_token, db_session):
    created = client.post(
        "/v1/agents/register",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"name": "agent-gamma", "wallet_address": "0x9999999999999999999999999999999999999999"},
    ).json()["agent"]
    resp = client.get(
        f"/v1/agents/{created['id']}", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert resp.status_code == 200
    assert resp.json()["id"] == created["id"]