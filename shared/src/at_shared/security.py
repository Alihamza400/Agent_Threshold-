"""Security primitives: password hashing (scrypt) and JWT tokens.

- scrypt (stdlib) — memory-hard KDF, no external C dependency.
- JWT (PyJWT) — signed access tokens carrying org_id + role scopes for RBAC.
Secrets come from `Settings`; production values from Vault/KMS.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt

from at_shared.config import get_settings

_scrypt_n = 2**14
_scrypt_r = 8
_scrypt_p = 1

ALGORITHMS_ALLOWED = ("HS256",)


# --------------------------------------------------------------------------
# Password hashing — scrypt (stdlib, memory-hard)
# --------------------------------------------------------------------------
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_scrypt_n,
        r=_scrypt_r,
        p=_scrypt_p,
        dklen=32,
    )
    return (
        f"scrypt${_scrypt_n}${_scrypt_r}${_scrypt_p}$"
        f"{base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt_b64, dk_b64 = stored.split("$")
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(dk_b64)
        dk = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
        )
        return hmac.compare_digest(dk, expected)
    except (ValueError, TypeError):
        return False


# --------------------------------------------------------------------------
# JWT access / refresh tokens
# --------------------------------------------------------------------------
def _now() -> datetime:
    return datetime.now(UTC)


def create_token(
    subject: str,
    claims: dict[str, Any],
    ttl_minutes: int,
    token_type: str,
) -> str:
    settings = get_settings()
    payload: dict[str, Any] = {
        "sub": subject,
        "type": token_type,
        "iat": _now(),
        "exp": _now() + timedelta(minutes=ttl_minutes),
        **claims,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(subject: str, claims: dict[str, Any]) -> str:
    s = get_settings()
    return create_token(subject, claims, s.jwt_access_ttl_minutes, "access")


def create_refresh_token(subject: str) -> str:
    s = get_settings()
    return create_token(subject, {}, s.jwt_refresh_ttl_hours, "refresh")


def decode_token(token: str, expected_type: str = "access") -> dict[str, Any]:
    """Decode and validate a token. Raises jwt.PyJWTError on failure."""
    settings = get_settings()
    payload = jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
        options={"require": ["sub", "type", "exp"]},
    )
    if payload.get("type") != expected_type:
        raise jwt.InvalidTokenError("unexpected token type")
    return payload