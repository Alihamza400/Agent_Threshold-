"""Orchestrator HTTP surface tests: API-key authz + scope enforcement."""

from __future__ import annotations

from at_shared.schemas.tx import ChainId

# Defined locally (not imported from conftest): pytest test directories share
# the `conftest` module name across services, so `from conftest import X` is
# shadowed when the full monorepo suite runs.
WALLET = "0x" + "1" * 40
KNOWN_CP = "0x" + "2" * 40


def _payload(agent_id):
    return {
        "agent_id": agent_id,
        "chain_id": ChainId.BASE.value,
        "from_address": WALLET,
        "to_address": KNOWN_CP,
        "value_wei": 10**16,
    }


def test_unknown_api_key_rejected(client):
    resp = client.post(
        "/v1/screen", headers={"X-API-Key": "at_invalid_does_not_exist"}, json=_payload("agent")
    )
    assert resp.status_code == 401


def test_scope_mismatch_rejects_fail_closed(client, org, make_agent, make_api_key):
    agent = make_agent(org.id, name="agent-key-scope")
    raw, _ = make_api_key(org.id, agent_ids=["00000000-0000-0000-0000-0000000000aa"])

    resp = client.post("/v1/screen", headers={"X-API-Key": raw}, json=_payload(agent.id))
    assert resp.status_code == 200
    body = resp.json()
    assert body["decision"] == "reject"
    assert any("scope" in r.lower() for r in body["reasons"])


def test_healthz(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
