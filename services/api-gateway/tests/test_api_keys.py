"""API key tests (FR-AUTH-01)."""

from __future__ import annotations

from at_shared.api_keys import hash_api_key
from at_shared.models import ApiKey


def test_create_api_key_returns_raw_once(client, admin_token):
    resp = client.post(
        "/v1/api-keys",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"name": "sdk-key", "agent_ids": []},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["api_key"].startswith("at_")
    assert body["agent_ids"] == []

    # raw key must NOT be retrievable again via the list endpoint
    listed = client.get("/v1/api-keys", headers={"Authorization": f"Bearer {admin_token}"}).json()
    assert all("api_key" not in k for k in listed)


def test_api_key_hash_stored_not_plaintext(client, admin_token, db_session):
    resp = client.post(
        "/v1/api-keys",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"name": "hashed-key", "agent_ids": []},
    )
    raw = resp.json()["api_key"]
    stored = db_session.query(ApiKey).filter_by(name="hashed-key").one()
    assert stored.key_hash == hash_api_key(raw)
    assert raw not in stored.key_hash  # prefix differs from full hash


def test_create_api_key_unknown_agent_rejected(client, admin_token):
    resp = client.post(
        "/v1/api-keys",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"name": "bad-scope", "agent_ids": ["does-not-exist"]},
    )
    assert resp.status_code == 400


def test_unknown_api_key_rejected(client):
    resp = client.get("/v1/auth/me", headers={"X-API-Key": "at_invalid_does_not_exist"})
    # API key is not a valid bearer credential -> 401
    assert resp.status_code == 401