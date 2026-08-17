"""Contract + security tests for the MCP server (tasks 4.3, 4.4, 4.5).

- 4.5: tool schemas are consistent across every supported chain
- FR-MCP-02: read-only tools only; unknown/write tools rejected
- 4.3: signed requests enforced; replay window; out-of-scope agents rejected
"""

from __future__ import annotations

import json
import time

from at_shared.schemas.tx import ChainId
from conftest import call_tool_headers

CT = {"Content-Type": "application/json", "Accept": "application/json"}


def _session(client, raw_key: str) -> str:
    """Initialize an MCP session, returning the Mcp-Session-Id."""
    init = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "pytest", "version": "0.0.1"},
            },
        }
    ).encode()
    resp = client.post("/mcp", content=init, headers={**call_tool_headers(raw_key, init), **CT})
    assert resp.status_code == 200, resp.text
    session_id = resp.headers.get("mcp-session-id")
    assert session_id, "no session id in initialize response"

    notif = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}).encode()
    client.post(
        "/mcp",
        content=notif,
        headers={**call_tool_headers(raw_key, notif), **CT, "Mcp-Session-Id": session_id},
    )
    return session_id


def _call(client, raw_key: str, name: str, arguments: dict, session_id: str):
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
    ).encode()
    return client.post(
        "/mcp",
        content=body,
        headers={**call_tool_headers(raw_key, body), **CT, "Mcp-Session-Id": session_id},
    )


def _result(resp) -> dict:
    data = resp.json()
    assert "result" in data, data
    return data["result"]


def _structured(result: dict) -> dict:
    assert result.get("isError") is False, result
    return result.get("structuredContent") or result["content"][0]


def test_tools_list_exposes_only_allowlisted(client, seed):
    session_id = _session(client, seed["raw_key"])
    body = json.dumps({"jsonrpc": "2.0", "id": 3, "method": "tools/list", "params": {}}).encode()
    resp = client.post(
        "/mcp",
        content=body,
        headers={**call_tool_headers(seed["raw_key"], body), **CT, "Mcp-Session-Id": session_id},
    )
    names = {t["name"] for t in _result(resp)["tools"]}
    assert names == {"simulate_transaction", "get_policy", "get_agent_history"}
    # no write tools exist
    assert not any(
        n.startswith(("write", "create", "update", "delete")) for n in names
    )


def test_simulate_schema_consistent_across_chains(client, seed):
    """FR-MCP-01 / 4.5: identical result schema for every supported chain."""
    session_id = _session(client, seed["raw_key"])
    agent_id = seed["agent_id"]
    for chain in ChainId:
        resp = _call(
            client,
            seed["raw_key"],
            "simulate_transaction",
            {
                "agent_id": agent_id,
                "chain_id": chain.value,
                "from_address": "0x1111111111111111111111111111111111111111",
                "to_address": "0x2222222222222222222222222222222222222222",
                "value_wei": 10**15,
                "calldata": None,
            },
            session_id,
        )
        structured = _structured(_result(resp))
        assert set(structured) == {
            "chain_id",
            "status",
            "gas_used_wei",
            "gas_ceiling_used",
            "state_diff",
            "revert_reason",
            "simulated_at",
            "simulator",
        }
        assert structured["chain_id"] == chain.value


def test_get_policy_read_only_returns_policy(client, seed):
    session_id = _session(client, seed["raw_key"])
    resp = _call(client, seed["raw_key"], "get_policy", {"agent_id": seed["agent_id"]}, session_id)
    structured = _structured(_result(resp))
    assert structured["agent_id"] == seed["agent_id"]
    assert structured["version"] == 1
    assert structured["gas_ceiling"] == 3_000_000


def test_unknown_tool_rejected(client, seed):
    """FR-MCP-02: non-allow-listed (e.g. write) tools rejected at the server."""
    session_id = _session(client, seed["raw_key"])
    resp = _call(client, seed["raw_key"], "update_policy", {"agent_id": seed["agent_id"]}, session_id)
    assert _result(resp)["isError"] is True


def test_out_of_scope_agent_rejected(client, seed, db_session):
    """Keys are scoped; another org's agent must be refused (fail-closed)."""
    session_id = _session(client, seed["raw_key"])
    from at_shared.models import Agent, Organization
    from at_shared.uuid7 import uuid7

    org2 = Organization(id=uuid7(), name="OtherOrg", tier="enterprise")
    db_session.add(org2)
    db_session.commit()
    other = Agent(
        id=uuid7(),
        org_id=org2.id,
        name="other",
        wallet_address="0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
    )
    db_session.add(other)
    db_session.commit()

    resp = _call(client, seed["raw_key"], "get_policy", {"agent_id": other.id}, session_id)
    result = _result(resp)
    assert result["isError"] is True
    assert "not in API key scope" in result["content"][0]["text"]


def test_signed_request_required(client, seed):
    """4.3: missing signature -> 401."""
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}).encode()
    resp = client.post("/mcp", content=body, headers={"X-API-Key": seed["raw_key"], **CT})
    assert resp.status_code == 401


def test_bad_signature_rejected(client, seed):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}).encode()
    headers = call_tool_headers(seed["raw_key"], body)
    headers["X-MCP-Signature"] = "0" * 64
    resp = client.post("/mcp", content=body, headers={**headers, **CT})
    assert resp.status_code == 401


def test_replay_window_enforced(client, seed):
    """4.3: an old timestamp is rejected (replay protection)."""
    from mcp_server.auth import compute_signature

    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}).encode()
    old_ts = str(int(time.time()) - 3600)
    sig = compute_signature(seed["raw_key"], old_ts, body)
    resp = client.post(
        "/mcp",
        content=body,
        headers={"X-API-Key": seed["raw_key"], "X-MCP-Timestamp": old_ts, "X-MCP-Signature": sig, **CT},
    )
    assert resp.status_code == 401


def test_health_ready(client):
    assert client.get("/healthz").json()["status"] == "ok"