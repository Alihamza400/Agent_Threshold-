"""Phase 3 pipeline integration tests: anomaly scorer + intent classifier in the screen path."""

from __future__ import annotations

import hashlib

from at_shared.models import Transaction

SELF = "0x4444444444444444444444444444444444444444"
NEW_CP = "0x8888888888888888888888888888888888888888"


def _setup(client, admin_token, name: str) -> tuple[str, str]:
    wallet = "0x" + hashlib.sha256(name.encode()).hexdigest()[:40]
    reg = client.post(
        "/v1/agents/register",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"name": name, "wallet_address": wallet},
    )
    assert reg.status_code == 201, reg.text
    agent_id = reg.json()["agent"]["id"]
    key = client.post(
        "/v1/api-keys",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"name": f"key-{name}", "agent_ids": [agent_id]},
    ).json()["api_key"]
    return agent_id, key


def test_intent_classifier_note_in_reasons(client, admin_token):
    agent_id, key = _setup(client, admin_token, "classifier-test")
    resp = client.post(
        "/v1/transactions/screen",
        headers={"X-API-Key": key},
        json={
            "agent_id": agent_id,
            "chain_id": "base",
            "from_address": SELF,
            "to_address": NEW_CP,
            "value_wei": 100000000000000000,
            "task_context": "perform a token swap of ETH to USDC",
        },
    )
    assert resp.status_code == 200, resp.text
    reasons = " ".join(resp.json()["reasons"])
    assert "intent=swap" in reasons  # deterministic mock classifier output


def test_anomaly_score_does_not_break_screen(client, admin_token):
    """A fresh agent has an empty baseline -> anomaly score 0, no crash."""
    agent_id, key = _setup(client, admin_token, "anomaly-test")
    resp = client.post(
        "/v1/transactions/screen",
        headers={"X-API-Key": key},
        json={
            "agent_id": agent_id,
            "chain_id": "base",
            "from_address": SELF,
            "to_address": NEW_CP,
            "value_wei": 10**16,
            "task_context": "transfer tokens",
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["decision"] in ("escalate", "reject", "approve")


def test_baseline_profile_persisted_after_screen(client, admin_token, db_session):
    agent_id, key = _setup(client, admin_token, "baseline-test")
    client.post(
        "/v1/transactions/screen",
        headers={"X-API-Key": key},
        json={
            "agent_id": agent_id,
            "chain_id": "base",
            "from_address": SELF,
            "to_address": NEW_CP,
            "value_wei": 10**16,
        },
    )
    # baseline profile row created (even if throttled to tx_count=0 initially)
    from at_shared.models import BaselineProfile
    from sqlalchemy import select

    profile = db_session.scalar(select(BaselineProfile).where(BaselineProfile.agent_id == agent_id))
    assert profile is not None
    assert profile.window_days == 90

    # transaction record persisted with decision
    tx = db_session.scalar(select(Transaction).where(Transaction.agent_id == agent_id))
    assert tx is not None
    assert tx.decision in ("approve", "reject", "escalate")