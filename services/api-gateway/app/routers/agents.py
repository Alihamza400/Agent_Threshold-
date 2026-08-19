"""Agent registration router (FR-ADMIN / Phase 1 walking skeleton).

POST /v1/agents/register creates an agent + default policy.
Returns 409 when the wallet is already registered for the org.
"""

from __future__ import annotations

from app.deps import require_admin
from at_shared.db import get_db
from at_shared.models import Agent, Organization, Policy
from at_shared.schemas.agent import AgentCreate, AgentRead, AgentRegistered
from at_shared.schemas.auth import CurrentUser
from at_shared.uuid7 import uuid7
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

router = APIRouter(prefix="/v1/agents", tags=["agents"])

# Conservative enterprise defaults for a freshly registered agent
DEFAULT_POLICY = {
    "spend_limit_usd": 100.0,
    "daily_spend_limit_usd": 1000.0,
    "allow_list": [],
    "deny_list": [],
    "rate_limit_per_minute": 30,
    "gas_ceiling": 100_000_000_000_000_000,  # 0.1 ETH
    "anomaly_threshold": 70.0,
}


@router.post("/register", response_model=AgentRegistered, status_code=status.HTTP_201_CREATED)
def register_agent(
    body: AgentCreate,
    db: Session = Depends(get_db),
    admin: CurrentUser = Depends(require_admin),
) -> AgentRegistered:
    existing = db.scalar(
        select(Agent).where(
            Agent.org_id == admin.org_id, Agent.wallet_address == body.wallet_address
        )
    )
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Wallet already registered for this org")

    org = db.get(Organization, admin.org_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organization not found")

    agent = Agent(
        id=uuid7(),
        org_id=admin.org_id,
        name=body.name,
        wallet_address=body.wallet_address,
        status="active",
        halted=False,
    )
    db.add(agent)
    db.flush()

    policy = Policy(
        id=uuid7(),
        agent_id=agent.id,
        version=1,
        created_by=admin.id,
        is_active=True,
        **DEFAULT_POLICY,
    )
    db.add(policy)

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Agent already registered") from exc

    db.refresh(agent)
    return AgentRegistered(agent=AgentRead.model_validate(agent), default_policy_id=policy.id)


@router.get("", response_model=list[AgentRead])
def list_agents(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_admin),
) -> list[AgentRead]:
    rows = db.scalars(
        select(Agent).where(Agent.org_id == user.org_id).order_by(Agent.created_at.asc())
    ).all()
    return [AgentRead.model_validate(a) for a in rows]


@router.get("/{agent_id}", response_model=AgentRead)
def get_agent(
    agent_id: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_admin),
) -> AgentRead:
    agent = db.scalar(select(Agent).where(Agent.id == agent_id))
    if agent is None or agent.org_id != user.org_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found")
    return AgentRead.model_validate(agent)
