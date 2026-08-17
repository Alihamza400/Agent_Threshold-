"""Shared FastAPI dependencies: authN (JWT + API key), RBAC, rate limiting."""

from __future__ import annotations

from datetime import UTC, datetime

import jwt as pyjwt
from at_shared.api_keys import hash_api_key
from at_shared.db import get_db
from at_shared.models import ApiKey, User
from at_shared.schemas.auth import CurrentUser
from at_shared.security import decode_token
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

bearer_scheme = HTTPBearer(auto_error=False)


def _unauthorized(detail: str = "Not authenticated") -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


def _forbidden(detail: str = "Insufficient permissions") -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


# --------------------------------------------------------------------------
# Bearer (JWT) — dashboard / SSO users
# --------------------------------------------------------------------------
def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> CurrentUser:
    if credentials is None:
        raise _unauthorized()
    try:
        payload = decode_token(credentials.credentials, "access")
    except pyjwt.PyJWTError as exc:
        raise _unauthorized("Invalid or expired token") from exc

    user_id = payload.get("sub")
    user = db.scalar(select(User).where(User.id == user_id))
    if user is None or not user.is_active:
        raise _unauthorized()
    return CurrentUser.model_validate(user)


def require_roles(*roles: str):
    """RBAC dependency factory (FR-AUTH-02). Returns a dependency."""

    def _checker(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in roles:
            raise _forbidden()
        return user

    return _checker


require_admin = require_roles("admin")
require_auditor_or_above = require_roles("admin", "approver", "auditor")


# --------------------------------------------------------------------------
# API key — service-to-service (SDK) auth, scoped to agents
# --------------------------------------------------------------------------
def get_api_key_context(
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict:
    """Resolve an API key to its org + scoped agent IDs.

    Fail-closed: unknown/inactive key -> 401; scope mismatch handled by caller.
    """
    raw_key = x_api_key
    if raw_key is None and authorization and authorization.lower().startswith("bearer "):
        raw_key = authorization[7:]
    if not raw_key:
        raise _unauthorized("API key required")

    key_hash = hash_api_key(raw_key)
    record = db.scalar(select(ApiKey).where(ApiKey.key_hash == key_hash))
    if record is None or not record.is_active:
        raise _unauthorized("Invalid API key")

    record.last_used_at = datetime.now(UTC)
    db.add(record)
    db.commit()
    return {"org_id": record.org_id, "agent_ids": set(record.agent_ids or [])}