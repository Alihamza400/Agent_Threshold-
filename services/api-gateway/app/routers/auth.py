"""Authentication router: login, refresh, current user."""

from __future__ import annotations

import jwt as pyjwt
from app.deps import get_current_user
from app.rate_limit import login_guard
from at_shared.config import get_settings
from at_shared.db import get_db
from at_shared.models import User
from at_shared.schemas.auth import (
    ChangePasswordRequest,
    CurrentUser,
    LoginRequest,
    RefreshRequest,
    TokenResponse,
)
from at_shared.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

router = APIRouter(prefix="/v1/auth", tags=["auth"])

_COOKIE_SAMESITE = "strict"
_COOKIE_PATH = "/"


def _set_auth_cookies(response: Response, tokens: TokenResponse, settings: object) -> None:
    """Set httpOnly, Secure, SameSite=Strict cookies for access and refresh tokens."""
    is_prod = getattr(settings, "is_production", False)
    response.set_cookie(
        key="at_access_token",
        value=tokens.access_token,
        httponly=True,
        secure=is_prod,
        samesite=_COOKIE_SAMESITE,
        path=_COOKIE_PATH,
        max_age=settings.jwt_access_ttl_minutes * 60,  # type: ignore[union-attr]
    )
    response.set_cookie(
        key="at_refresh_token",
        value=tokens.refresh_token,
        httponly=True,
        secure=is_prod,
        samesite=_COOKIE_SAMESITE,
        path=_COOKIE_PATH,
        max_age=settings.jwt_refresh_ttl_hours * 3600,  # type: ignore[union-attr]
    )


def _clear_auth_cookies(response: Response) -> None:
    """Expire auth cookies on logout."""
    response.delete_cookie("at_access_token", path=_COOKIE_PATH)
    response.delete_cookie("at_refresh_token", path=_COOKIE_PATH)


def _issue_tokens(user: User, must_change_password: bool = False) -> TokenResponse:
    claims = {"org_id": user.org_id, "role": user.role}
    access = create_access_token(user.id, claims)
    refresh = create_refresh_token(user.id)
    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        expires_in=get_settings().jwt_access_ttl_minutes * 60,
        must_change_password=must_change_password,
    )


@router.post("/login", response_model=TokenResponse)
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    _: None = Depends(login_guard),
) -> TokenResponse:
    settings = get_settings()
    user = db.scalar(select(User).where(User.email == body.email))
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    if user.password_hash is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    tokens = _issue_tokens(user, must_change_password=user.must_change_password)
    _set_auth_cookies(response, tokens, settings)
    return tokens


@router.post("/refresh", response_model=TokenResponse)
def refresh(
    body: RefreshRequest,
    response: Response,
    request: Request,
    db: Session = Depends(get_db),
) -> TokenResponse:
    settings = get_settings()
    # Accept refresh token from body or cookie
    raw_token = body.refresh_token
    if not raw_token:
        raw_token = request.cookies.get("at_refresh_token", "")
    if not raw_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Refresh token required")
    try:
        payload = decode_token(raw_token, "refresh")
    except pyjwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh token") from exc
    user = db.scalar(select(User).where(User.id == payload.get("sub")))
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User inactive")
    tokens = _issue_tokens(user, must_change_password=user.must_change_password)
    _set_auth_cookies(response, tokens, settings)
    return tokens


@router.post("/logout")
def logout(response: Response) -> dict:
    _clear_auth_cookies(response)
    return {"detail": "logged out"}


@router.post("/change-password")
def change_password(
    body: ChangePasswordRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Change password. Required on first login with bootstrap password."""
    db_user = db.scalar(select(User).where(User.id == user.id))
    if db_user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    if db_user.password_hash is None or not verify_password(body.current_password, db_user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Current password is incorrect")
    db_user.password_hash = hash_password(body.new_password)
    db_user.must_change_password = False
    db.add(db_user)
    db.commit()
    return {"detail": "password changed"}


@router.get("/me", response_model=CurrentUser)
def me(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    return user
