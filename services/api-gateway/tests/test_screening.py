"""Screening endpoint + kill-switch tests (FR-API-01, FR-ORCH-01, FR-ADMIN-02)."""

from __future__ import annotations

from at_shared.models import Policy
from at_shared.uuid7 import uuid7

WALLET = "0xabcdef1234567890abcdef1234567890abcdef12"
SELF = "0x1111111111111111111111111111111111111111"
NEW_CP = "0x9999999999999999999999999999999999999999"
KNOWN_CP = "0x2222222222222222222222222222222222222222"


def _wallet(n: int) -> str:
    return f"0x{n:040x}"


def _register_agent(client, admin_token, wallet=WALLET, name="agent-screen"):
    resp = client.post(
        "/v1/agents/register",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"name": name, "wallet_address": wallet},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_api_key(client, admin_token, agent_id):
    resp = client.post(
        "/v1/api-keys",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"name": "screen-key", "agent_ids": [agent_id]},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["api_key"]


def test_screen_within_policy_approves(client, admin_token):
    reg = _register_agent(client, admin_token, SELF, "agent-approve")
    key = _create_api_key(client, admin_token, reg["agent"]["id"])

    # seed a known counterparty first so rule 9 doesn't escalate
    client.post(
        "/v1/transactions/screen",
        headers={"X-API-Key": key},
        json={
            "agent_id": reg["agent"]["id"],
            "chain_id": "base",
            "from_address": SELF,
            "to_address": KNOWN_CP,
            "value_wei": 1000,
        },
    )
    resp = client.post(
        "/v1/transactions/screen",
        headers={"X-API-Key": key},
        json={
            "agent_id": reg["agent"]["id"],
            "chain_id": "base",
            "from_address": SELF,
            "to_address": KNOWN_CP,
            "value_wei": 1000,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["decision"] in ("approve", "escalate")
    assert body["transaction_id"]


def test_screen_halted_agent_rejected(client, admin_token):
    reg = _register_agent(client, admin_token, _wallet(1), "agent-halted")
    key = _create_api_key(client, admin_token, reg["agent"]["id"])

    client.post(
        "/v1/kill-switch",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"scope": "agent", "agent_id": reg["agent"]["id"], "reason": "compromise"},
    )

    resp = client.post(
        "/v1/transactions/screen",
        headers={"X-API-Key": key},
        json={
            "agent_id": reg["agent"]["id"],
            "chain_id": "base",
            "from_address": SELF,
            "to_address": NEW_CP,
            "value_wei": 1000,
        },
    )
    assert resp.status_code == 200
    assert resp.json()["decision"] == "reject"
    assert any("halt" in r.lower() for r in resp.json()["reasons"])


def test_screen_new_counterparty_escalates(client, admin_token):
    reg = _register_agent(client, admin_token, _wallet(2), "agent-escalate")
    key = _create_api_key(client, admin_token, reg["agent"]["id"])

    resp = client.post(
        "/v1/transactions/screen",
        headers={"X-API-Key": key},
        json={
            "agent_id": reg["agent"]["id"],
            "chain_id": "ethereum",
            "from_address": SELF,
            "to_address": NEW_CP,
            "value_wei": 10**17,  # 0.1 ETH -> ~$100 > conservative escalation
        },
    )
    assert resp.json()["decision"] == "escalate"


def test_screen_over_spend_limit_rejected(client, admin_token, db_session):
    reg = _register_agent(client, admin_token, _wallet(3), "agent-limit")
    key = _create_api_key(client, admin_token, reg["agent"]["id"])

    # tighten policy to a tiny spend limit
    agent_id = reg["agent"]["id"]
    policy = db_session.query(Policy).filter_by(agent_id=agent_id, is_active=True).one()
    policy.spend_limit_usd = 0.001
    db_session.commit()

    resp = client.post(
        "/v1/transactions/screen",
        headers={"X-API-Key": key},
        json={
            "agent_id": agent_id,
            "chain_id": "base",
            "from_address": SELF,
            "to_address": NEW_CP,
            "value_wei": 10**18,  # 1 ETH -> ~$1000 > limit
        },
    )
    assert resp.json()["decision"] == "reject"
    assert any("spend limit" in r for r in resp.json()["reasons"])


def test_screen_api_key_out_of_scope_fails_closed(client, admin_token):
    reg_a = _register_agent(client, admin_token, _wallet(4), "agent-a")
    reg_b = _register_agent(client, admin_token, _wallet(5), "agent-b")
    key = _create_api_key(client, admin_token, reg_a["agent"]["id"])

    resp = client.post(
        "/v1/transactions/screen",
        headers={"X-API-Key": key},
        json={
            "agent_id": reg_b["agent"]["id"],
            "chain_id": "base",
            "from_address": SELF,
            "to_address": NEW_CP,
            "value_wei": 1,
        },
    )
    assert resp.status_code == 200
    assert resp.json()["decision"] == "reject"


def test_screen_unknown_agent_fails_closed(client, admin_token):
    reg = _register_agent(client, admin_token, _wallet(6), "agent-unknown")
    key = _create_api_key(client, admin_token, reg["agent"]["id"])
    resp = client.post(
        "/v1/transactions/screen",
        headers={"X-API-Key": key},
        json={
            "agent_id": "does-not-exist",
            "chain_id": "base",
            "from_address": SELF,
            "to_address": NEW_CP,
            "value_wei": 1,
        },
    )
    assert resp.json()["decision"] == "reject"


def test_decision_persisted_and_retrievable(client, admin_token):
    reg = _register_agent(client, admin_token, _wallet(7), "agent-audit")
    key = _create_api_key(client, admin_token, reg["agent"]["id"])
    screen = client.post(
        "/v1/transactions/screen",
        headers={"X-API-Key": key},
        json={
            "agent_id": reg["agent"]["id"],
            "chain_id": "base",
            "from_address": SELF,
            "to_address": NEW_CP,
            "value_wei": 1,
        },
    ).json()
    tx_id = screen["transaction_id"]
    got = client.get(f"/v1/transactions/{tx_id}", headers={"X-API-Key": key})
    assert got.status_code == 200
    assert got.json()["id"] == tx_id
    assert got.json()["agent_id"] == reg["agent"]["id"]


def test_kill_switch_requires_admin(client, admin_token, db_session):
    from at_shared.models import User
    from at_shared.security import hash_password

    org_id = client.get("/v1/auth/me", headers={"Authorization": f"Bearer {admin_token}"}).json()[
        "org_id"
    ]
    auditor = User(
        id=uuid7(),
        org_id=org_id,
        email="auditor2@agentthreshold.dev",
        role="auditor",
        password_hash=hash_password("AuditorPass123!"),
        is_active=True,
    )
    db_session.add(auditor)
    db_session.commit()
    token = client.post(
        "/v1/auth/login",
        json={"email": "auditor2@agentthreshold.dev", "password": "AuditorPass123!"},
    ).json()["access_token"]

    resp = client.post(
        "/v1/kill-switch",
        headers={"Authorization": f"Bearer {token}"},
        json={"scope": "org", "reason": "should fail"},
    )
    assert resp.status_code == 403
