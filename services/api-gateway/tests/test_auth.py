"""Auth + RBAC tests (FR-AUTH-01, FR-AUTH-02)."""

from __future__ import annotations

from at_shared.models import User
from at_shared.security import hash_password
from at_shared.uuid7 import uuid7


def test_login_success(client, admin_token):
    assert admin_token


def test_login_invalid_password(client):
    resp = client.post(
        "/v1/auth/login",
        json={"email": "admin@agentthreshold.dev", "password": "WrongPass123!"},
    )
    assert resp.status_code == 401


def test_login_invalid_email_format(client):
    resp = client.post(
        "/v1/auth/login", json={"email": "not-an-email", "password": "whatever123"}
    )
    assert resp.status_code == 422


def test_me(client, admin_token):
    resp = client.get("/v1/auth/me", headers={"Authorization": f"Bearer {admin_token}"})
    assert resp.status_code == 200
    assert resp.json()["role"] == "admin"
    assert resp.json()["org_id"]


def test_me_unauthenticated(client):
    resp = client.get("/v1/auth/me")
    assert resp.status_code == 401


def test_me_invalid_token(client):
    resp = client.get("/v1/auth/me", headers={"Authorization": "Bearer not.a.valid.token"})
    assert resp.status_code == 401


def test_auditor_cannot_write_policies(client, admin_token, db_session):
    """FR-AUTH-02: Auditor role cannot call policy-write endpoints."""
    org_id = client.get("/v1/auth/me", headers={"Authorization": f"Bearer {admin_token}"}).json()[
        "org_id"
    ]
    auditor = User(
        id=uuid7(),
        org_id=org_id,
        email="auditor@agentthreshold.dev",
        role="auditor",
        password_hash=hash_password("AuditorPass123!"),
        is_active=True,
    )
    db_session.add(auditor)
    db_session.commit()

    login = client.post(
        "/v1/auth/login",
        json={"email": "auditor@agentthreshold.dev", "password": "AuditorPass123!"},
    )
    auditor_token = login.json()["access_token"]

    resp = client.post(
        "/v1/agents/register",
        headers={"Authorization": f"Bearer {auditor_token}"},
        json={
            "name": "should-fail",
            "wallet_address": "0x0000000000000000000000000000000000000000",
        },
    )
    assert resp.status_code == 403