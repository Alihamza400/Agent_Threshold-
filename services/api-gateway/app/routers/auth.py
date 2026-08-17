"""Authentication router: login, refresh, current user."""

from __future__ import annotations

import jwt as pyjwt
from app.deps import get_current_user
from at_shared.config import get_settings
from at_shared.db import get_db
from at_shared.models import User
from at_shared.schemas.auth import (
    CurrentUser,
    LoginRequest,
    RefreshRequest,
    TokenResponse,
)
from at_shared.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_password,
)
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

router = APIRouter(prefix="/v1/auth", tags=["auth"])


def _issue_tokens(user: User) -> TokenResponse:
    claims = {"org_id": user.org_id, "role": user.role}
    access = create_access_token(user.id, claims)
    refresh = create_refresh_token(user.id)
    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        expires_in=get_settings().jwt_access_ttl_minutes * 60,
    )


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.scalar(select(User).where(User.email == body.email))
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    if user.password_hash is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    return _issue_tokens(user)


@router.post("/refresh", response_model=TokenResponse)
def refresh(body: RefreshRequest, db: Session = Depends(get_db)) -> TokenResponse:
    try:
        payload = decode_token(body.refresh_token, "refresh")
    except pyjwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh token") from exc
    user = db.scalar(select(User).where(User.id == payload.get("sub")))
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User inactive")
    return _issue_tokens(user)


@router.get("/me", response_model=CurrentUser)
def me(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    return user