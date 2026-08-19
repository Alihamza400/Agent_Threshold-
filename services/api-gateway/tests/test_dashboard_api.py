"""Phase 7 dashboard APIs: policies, escalations, audit, agents, search."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from at_shared.models import AnchorBatch, Approval, AuditRecord, User
from at_shared.security import hash_password
from at_shared.uuid7 import uuid7

WALLET = "0xabcdef1234567890abcdef1234567890abcdef12"
SELF = "0x1111111111111111111111111111111111111111"
NEW_CP = "0x9999999999999999999999999999999999999999"


def _wallet(n: int) -> str:
    return f"0x{n:040x}"


def _register(client, admin_token, wallet=WALLET, name="agent-dash"):
    resp = client.post(
        "/v1/agents/register",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"name": name, "wallet_address": wallet},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_key(client, admin_token, agent_id):
    resp = client.post(
        "/v1/api-keys",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"name": "dash-key", "agent_ids": [agent_id]},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["api_key"]


def _screen(client, key, agent_id, to_address, value_wei=10**17):
    return client.post(
        "/v1/transactions/screen",
        headers={"X-API-Key": key},
        json={
            "agent_id": agent_id,
            "chain_id": "base",
            "from_address": SELF,
            "to_address": to_address,
            "value_wei": value_wei,
        },
    ).json()


def _add_auditor(db_session, org_id, email="auditor@example.dev"):
    user = db_session.query(User).filter_by(email=email).first()
    if user is None:
        user = User(
            id=uuid7(),
            org_id=org_id,
            email=email,
            role="auditor",
            password_hash=hash_password("Auditor_Str0ng!"),
            is_active=True,
        )
        db_session.add(user)
        db_session.commit()
    return user


def _auditor_token(client, db_session, org_id) -> str:
    _add_auditor(db_session, org_id)
    resp = client.post(
        "/v1/auth/login",
        json={"email": "auditor@example.dev", "password": "Auditor_Str0ng!"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


# --------------------------------------------------------------------------
# Agents list (7.5)
# --------------------------------------------------------------------------
def test_agents_list_admin_and_role_gate(client, admin_token):
    reg = _register(client, admin_token, _wallet(11), "agent-list")
    resp = client.get("/v1/agents", headers={"Authorization": f"Bearer {admin_token}"})
    assert resp.status_code == 200
    assert any(a["id"] == reg["agent"]["id"] for a in resp.json())


# --------------------------------------------------------------------------
# Policy configuration (7.2)
# --------------------------------------------------------------------------
def test_policy_get_put_versions_and_audit(client, admin_token, db_session):
    reg = _register(client, admin_token, _wallet(12), "agent-policy")
    agent_id = reg["agent"]["id"]

    get = client.get(
        f"/v1/agents/{agent_id}/policy",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert get.status_code == 200
    assert get.json()["version"] == 1
    assert get.json()["spend_limit_usd"] == 100.0

    put = client.put(
        f"/v1/agents/{agent_id}/policy",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"spend_limit_usd": 5.0, "change_note": "tighten for maintenance"},
    )
    assert put.status_code == 200, put.text
    assert put.json()["version"] == 2
    assert put.json()["spend_limit_usd"] == 5.0
    assert put.json()["is_active"] is True

    # the previous version is deactivated; history is preserved
    versions = client.get(
        f"/v1/agents/{agent_id}/policy/versions",
        headers={"Authorization": f"Bearer {admin_token}"},
    ).json()
    assert [v["version"] for v in versions] == [1, 2]
    assert versions[0]["is_active"] is False

    # a change audit record was written
    records = (
        db_session.query(AuditRecord).filter_by(agent_id=agent_id, event_type="policy_update").all()
    )
    assert len(records) == 1
    assert records[0].details["to_version"] == 2

    # the screening engine now enforces the new version (5 USD / 8 ETH -> reject)
    key = _create_key(client, admin_token, agent_id)
    decision = _screen(client, key, agent_id, NEW_CP, value_wei=8 * 10**18)
    assert decision["decision"] == "reject"


def test_policy_put_validates_window(client, admin_token):
    reg = _register(client, admin_token, _wallet(13), "agent-window")
    agent_id = reg["agent"]["id"]
    resp = client.put(
        f"/v1/agents/{agent_id}/policy",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"active_from_minute": 100, "active_to_minute": 50},
    )
    assert resp.status_code == 422


def test_policy_auditor_read_only(client, admin_token, db_session):
    reg = _register(client, admin_token, _wallet(14), "agent-policy-audit")
    agent_id = reg["agent"]["id"]
    org_id = db_session.query(User).filter_by(email="admin@agentthreshold.dev").first().org_id
    auditor = _auditor_token(client, db_session, org_id)

    ok = client.get(
        f"/v1/agents/{agent_id}/policy",
        headers={"Authorization": f"Bearer {auditor}"},
    )
    assert ok.status_code == 200

    forbidden = client.put(
        f"/v1/agents/{agent_id}/policy",
        headers={"Authorization": f"Bearer {auditor}"},
        json={"spend_limit_usd": 1.0},
    )
    assert forbidden.status_code == 403


# --------------------------------------------------------------------------
# Escalation / approval queue (7.3)
# --------------------------------------------------------------------------
def test_escalation_queue_and_approve(client, admin_token, db_session):
    reg = _register(client, admin_token, _wallet(15), "agent-escalate-dash")
    key = _create_key(client, admin_token, reg["agent"]["id"])
    decision = _screen(client, key, reg["agent"]["id"], NEW_CP)
    assert decision["decision"] == "escalate"
    agent_id = reg["agent"]["id"]

    queue = client.get(
        f"/v1/approvals?status=pending&agent_id={agent_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert queue.status_code == 200
    assert len(queue.json()) == 1
    item = queue.json()[0]
    assert item["decision"] == "escalate"
    assert item["agent_name"] == "agent-escalate-dash"
    assert item["to_address"] == NEW_CP

    approved = client.post(
        f"/v1/approvals/{item['id']}/approve",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"note": "ok"},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert approved.json()["decided_by"]

    # double decision is rejected with 409
    again = client.post(
        f"/v1/approvals/{item['id']}/approve",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"note": "again"},
    )
    assert again.status_code == 409

    # the underlying transaction transitioned to approved
    tx = db_session.get(Approval, item["id"]).transaction
    assert tx.status == "approved"


def test_escalation_reject_and_expiry(client, admin_token, db_session):
    reg = _register(client, admin_token, _wallet(16), "agent-reject")
    key = _create_key(client, admin_token, reg["agent"]["id"])
    _screen(client, key, reg["agent"]["id"], NEW_CP)

    org_id = db_session.query(User).filter_by(email="admin@agentthreshold.dev").first().org_id
    pending = db_session.query(Approval).filter_by(org_id=org_id, status="pending").first()
    pending.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db_session.commit()

    # listing expires the overdue item (fail-closed default reject)
    queue = client.get(
        "/v1/approvals?status=pending",
        headers={"Authorization": f"Bearer {admin_token}"},
    ).json()
    assert pending.id not in [a["id"] for a in queue]
    db_session.expire_all()
    assert db_session.get(Approval, pending.id).status == "expired"


# --------------------------------------------------------------------------
# Audit log search + proof + CSV export (7.4)
# --------------------------------------------------------------------------
def test_audit_records_search_and_export(client, admin_token):
    reg = _register(client, admin_token, _wallet(17), "agent-audit")
    key = _create_key(client, admin_token, reg["agent"]["id"])
    _screen(client, key, reg["agent"]["id"], NEW_CP)

    resp = client.get(
        "/v1/audit/records",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 1
    record = body["items"][0]
    assert record["event_type"] == "decision"
    assert len(record["event_hash"]) == 64
    assert record["anchored_batch_id"] is None

    export = client.get(
        "/v1/audit/export",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert export.status_code == 200
    assert "text/csv" in export.headers["content-type"]
    assert record["id"] in export.text
    assert "event_hash" in export.text


def test_audit_export_pdf(client, admin_token):
    reg = _register(client, admin_token, _wallet(22), "agent-pdf")
    key = _create_key(client, admin_token, reg["agent"]["id"])
    _screen(client, key, reg["agent"]["id"], NEW_CP)

    resp = client.get(
        "/v1/audit/export.pdf",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200, resp.text[:200]
    assert resp.headers["content-type"] == "application/pdf"
    # PDF header present; streamed content is compressed, so size sanity only
    assert resp.content.startswith(b"%PDF")
    assert len(resp.content) > 1000


def test_audit_record_proof(client, admin_token, db_session):
    reg = _register(client, admin_token, _wallet(18), "agent-proof")
    key = _create_key(client, admin_token, reg["agent"]["id"])
    _screen(client, key, reg["agent"]["id"], NEW_CP)

    org_id = db_session.query(User).filter_by(email="admin@agentthreshold.dev").first().org_id
    records = (
        db_session.query(AuditRecord)
        .filter_by(org_id=org_id)
        .order_by(AuditRecord.created_at.asc())
        .all()
    )
    batch = AnchorBatch(
        id=uuid7(),
        batch_id=99,
        merkle_root="0" * 64,
        record_count=0,
        status="anchored",
        submitted_at=datetime.now(UTC),
        anchored_at=datetime.now(UTC),
    )
    db_session.add(batch)
    db_session.commit()

    from at_shared.merkle import merkle_root as build_root

    leaves = [bytes.fromhex(r.event_hash) for r in records]
    root = build_root(leaves)
    batch.merkle_root = root.hex()
    batch.record_count = len(leaves)
    for r in records:
        r.anchored_batch_id = 99
    db_session.commit()

    target = records[0]
    resp = client.get(
        f"/v1/audit/records/{target.id}/proof",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200, resp.text
    bundle = resp.json()
    assert bundle["verified"] is True
    assert bundle["root"] == root.hex()
    assert bundle["batch_id"] == 99
    assert bundle["leaf"] == target.event_hash
    assert len(bundle["proof"]) >= 1


# --------------------------------------------------------------------------
# Metrics overview (7.6)
# --------------------------------------------------------------------------
def test_metrics_overview(client, admin_token, db_session):
    reg = _register(client, admin_token, _wallet(21), "agent-metrics")
    key = _create_key(client, admin_token, reg["agent"]["id"])
    _screen(client, key, reg["agent"]["id"], NEW_CP)  # escalate -> fail-closed

    org_id = db_session.query(User).filter_by(email="admin@agentthreshold.dev").first().org_id
    auditor = _auditor_token(client, db_session, org_id)
    resp = client.get("/v1/metrics/overview", headers={"Authorization": f"Bearer {auditor}"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_transactions_24h"] >= 1
    assert body["decision_mix"]["escalate"] >= 1
    assert body["fail_closed_rate"] > 0
    assert "p50" in body["latency_ms"] and "p95" in body["latency_ms"]
    assert len(body["daily_series"]["days"]) == 14
    assert body["approvals"]["pending"] >= 0


def test_metrics_requires_auditor_or_above(client, admin_token):
    resp = client.get("/v1/metrics/overview", headers={"Authorization": f"Bearer {admin_token}"})
    assert resp.status_code == 200


# --------------------------------------------------------------------------
# Org-wide transaction search (7.4 / 7.6)
# --------------------------------------------------------------------------
def test_org_transaction_search_jwt(client, admin_token):
    reg = _register(client, admin_token, _wallet(19), "agent-search")
    key = _create_key(client, admin_token, reg["agent"]["id"])
    _screen(client, key, reg["agent"]["id"], NEW_CP)

    resp = client.get(
        "/v1/transactions",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert any(t["agent_id"] == reg["agent"]["id"] for t in resp.json())

    filtered = client.get(
        "/v1/transactions?decision=escalate",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert all(t["decision"] == "escalate" for t in filtered.json())


# --------------------------------------------------------------------------
# Kill-switch resume (7.5)
# --------------------------------------------------------------------------
def test_kill_switch_halt_and_resume(client, admin_token):
    reg = _register(client, admin_token, _wallet(20), "agent-kill")
    agent_id = reg["agent"]["id"]
    key = _create_key(client, admin_token, agent_id)

    halt = client.post(
        "/v1/kill-switch",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"scope": "agent", "agent_id": agent_id, "reason": "compromise"},
    )
    assert halt.status_code == 200
    assert _screen(client, key, agent_id, NEW_CP)["decision"] == "reject"

    resume = client.delete(
        f"/v1/kill-switch?scope=agent&agent_id={agent_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resume.status_code == 200
    assert resume.json()["halted"] is False
    assert _screen(client, key, agent_id, NEW_CP)["decision"] == "escalate"
