"""Policy configuration API (Phase 7.2 — versioned, append-only).

GET  /v1/agents/{agent_id}/policy              active policy (read)
GET  /v1/agents/{agent_id}/policy/versions     full history (read)
PUT  /v1/agents/{agent_id}/policy              publish a new version

Publishing is atomic: the new version is written with `is_active=True`, the
previous active version is deactivated, and an immutable audit record is
written in the same transaction — so the screening engine can never observe a
half-applied change (FR-POL-02 change notification via audit trail).
"""

from __future__ import annotations

from app.deps import require_admin, require_auditor_or_above
from at_shared.audit_events import audit_leaf, write_audit_record
from at_shared.db import get_db
from at_shared.models import Agent, Policy
from at_shared.schemas.auth import CurrentUser
from at_shared.schemas.policy import PolicyRead, PolicyUpdate
from at_shared.uuid7 import uuid7
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

router = APIRouter(prefix="/v1/agents", tags=["policies"])


def _get_agent(db: Session, agent_id: str, org_id: str) -> Agent:
    agent = db.scalar(select(Agent).where(Agent.id == agent_id, Agent.org_id == org_id))
    if agent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found")
    return agent


def _get_active_policy(db: Session, agent_id: str) -> Policy | None:
    return db.scalar(
        select(Policy)
        .where(Policy.agent_id == agent_id, Policy.is_active.is_(True))
        .order_by(Policy.version.desc())
        .limit(1)
    )


@router.get("/{agent_id}/policy", response_model=PolicyRead)
def get_policy(
    agent_id: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_auditor_or_above),
) -> PolicyRead:
    _get_agent(db, agent_id, user.org_id)
    policy = _get_active_policy(db, agent_id)
    if policy is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No active policy for agent")
    return PolicyRead.model_validate(policy)


@router.get("/{agent_id}/policy/versions", response_model=list[PolicyRead])
def list_policy_versions(
    agent_id: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_auditor_or_above),
) -> list[PolicyRead]:
    _get_agent(db, agent_id, user.org_id)
    rows = db.scalars(
        select(Policy).where(Policy.agent_id == agent_id).order_by(Policy.version.asc())
    ).all()
    return [PolicyRead.model_validate(r) for r in rows]


@router.put("/{agent_id}/policy", response_model=PolicyRead)
def update_policy(
    agent_id: str,
    body: PolicyUpdate,
    db: Session = Depends(get_db),
    admin: CurrentUser = Depends(require_admin),
) -> PolicyRead:
    _get_agent(db, agent_id, admin.org_id)
    current = _get_active_policy(db, agent_id)
    if current is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No active policy for agent")

    next_fields = {
        "spend_limit_usd": body.spend_limit_usd
        if body.spend_limit_usd is not None
        else current.spend_limit_usd,
        "daily_spend_limit_usd": body.daily_spend_limit_usd
        if body.daily_spend_limit_usd is not None
        else current.daily_spend_limit_usd,
        "allow_list": body.allow_list
        if body.allow_list is not None
        else (current.allow_list or []),
        "deny_list": body.deny_list if body.deny_list is not None else (current.deny_list or []),
        "rate_limit_per_minute": body.rate_limit_per_minute
        if body.rate_limit_per_minute is not None
        else current.rate_limit_per_minute,
        "active_from_minute": body.active_from_minute
        if body.active_from_minute is not None
        else current.active_from_minute,
        "active_to_minute": body.active_to_minute
        if body.active_to_minute is not None
        else current.active_to_minute,
        "gas_ceiling": body.gas_ceiling if body.gas_ceiling is not None else current.gas_ceiling,
        "anomaly_threshold": body.anomaly_threshold,
    }

    next_version = current.version + 1
    new_policy = Policy(
        id=uuid7(),
        agent_id=agent_id,
        version=next_version,
        created_by=admin.id,
        is_active=True,
        **next_fields,
    )
    current.is_active = False
    db.add(new_policy)
    db.flush()

    leaf = audit_leaf(
        "policy_update",
        admin.org_id,
        agent_id,
        next_version,
        next_fields["spend_limit_usd"],
        next_fields["daily_spend_limit_usd"],
    )
    write_audit_record(
        db,
        org_id=admin.org_id,
        agent_id=agent_id,
        transaction_id=None,
        event_type="policy_update",
        details={
            "actor_id": admin.id,
            "actor_email": admin.email,
            "agent_id": agent_id,
            "from_version": current.version,
            "to_version": next_version,
            "change_note": body.change_note,
            "fields": {k: v for k, v in next_fields.items()},
        },
        leaf=leaf,
    )
    db.commit()
    db.refresh(new_policy)
    return PolicyRead.model_validate(new_policy)
