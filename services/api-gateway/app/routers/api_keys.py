"""API key router (FR-AUTH-01): scoped keys for service-to-service (SDK) auth."""

from __future__ import annotations

from app.deps import require_admin
from at_shared.api_keys import generate_api_key, hash_api_key
from at_shared.db import get_db
from at_shared.models import Agent, ApiKey
from at_shared.schemas.auth import ApiKeyCreate, ApiKeyCreated, ApiKeyRead, CurrentUser
from at_shared.uuid7 import uuid7
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

router = APIRouter(prefix="/v1/api-keys", tags=["api-keys"])


@router.post("", response_model=ApiKeyCreated, status_code=status.HTTP_201_CREATED)
def create_api_key(
    body: ApiKeyCreate,
    db: Session = Depends(get_db),
    admin: CurrentUser = Depends(require_admin),
) -> ApiKeyCreated:
    if body.agent_ids:
        owned = {
            aid for (aid,) in db.execute(select(Agent.id).where(Agent.org_id == admin.org_id)).all()
        }
        unknown = set(body.agent_ids) - owned
        if unknown:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, f"Unknown agent ids: {sorted(unknown)}"
            )

    raw_key, prefix = generate_api_key()
    record = ApiKey(
        id=uuid7(),
        org_id=admin.org_id,
        name=body.name,
        key_hash=hash_api_key(raw_key),
        key_prefix=prefix,
        agent_ids=body.agent_ids,
        is_active=True,
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    return ApiKeyCreated(
        id=record.id,
        name=record.name,
        agent_ids=record.agent_ids,
        created_at=record.created_at,
        api_key=raw_key,  # shown exactly once
    )


@router.get("", response_model=list[ApiKeyRead])
def list_api_keys(
    db: Session = Depends(get_db),
    admin: CurrentUser = Depends(require_admin),
) -> list[ApiKeyRead]:
    keys = db.scalars(select(ApiKey).where(ApiKey.org_id == admin.org_id)).all()
    return [ApiKeyRead.model_validate(k) for k in keys]
