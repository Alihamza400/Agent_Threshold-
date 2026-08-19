"""API-key authN for the orchestrator service (service-to-service).

Mirrors the api-gateway's scoped API key check so the orchestrator can be
deployed independently and still enforce org + agent scope (FR-AUTH-01,
FR-AUTH-02). Fail-closed: unknown/inactive key -> 401.
"""

from __future__ import annotations

from datetime import UTC, datetime

from at_shared.api_keys import hash_api_key
from at_shared.db import get_db
from at_shared.models import ApiKey
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session


def _unauthorized(detail: str = "Not authenticated") -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


def get_api_key_context(
    x_api_key: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict:
    """Resolve an API key to its org + scoped agent IDs."""
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
