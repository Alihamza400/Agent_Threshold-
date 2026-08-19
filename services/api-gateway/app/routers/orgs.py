"""Organization router: bootstrap and org management (Phase 1)."""

from __future__ import annotations

from app.deps import require_admin
from at_shared.db import get_db
from at_shared.models import Organization
from at_shared.schemas.agent import OrganizationRead
from at_shared.schemas.auth import CurrentUser
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

router = APIRouter(prefix="/v1/orgs", tags=["orgs"])


@router.get("/me", response_model=OrganizationRead)
def my_org(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_admin),
) -> OrganizationRead:
    org = db.get(Organization, user.org_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organization not found")
    return OrganizationRead.model_validate(org)
