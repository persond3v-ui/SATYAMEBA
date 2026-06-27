"""Internal endpoints consumed by the JupyterHub authenticator.

The Hub's custom authenticator posts (username, handshake) here; we confirm the
handshake HMAC and that the user is approved. This keeps the source of truth for
identity in the gateway DB while letting the Hub remain the execution engine.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..models import SsoToken, User, UserRole, UserStatus
from ..security import verify_internal_token, verify_password
from ..timeutil import aware, utcnow

router = APIRouter(prefix="/api/internal", tags=["internal"])
settings = get_settings()


@router.post("/redeem-ott")
def redeem_ott(
    body: dict,
    x_sat_internal: str = Header(default=""),
    db: Session = Depends(get_db),
):
    """Redeem a single-use SSO token (called by the Hub's SSO login handler).

    Validates the token is present, unused and unexpired, marks it used, and
    returns the Hub identity for the still-approved user.
    """
    if x_sat_internal != settings.internal_shared_secret:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad internal auth")
    token = (body or {}).get("token", "")
    row = db.get(SsoToken, token)
    if row is None or row.used or aware(row.expires_at) < utcnow():
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or expired token")
    row.used = True
    db.commit()
    user = db.execute(
        select(User).where(User.username == row.username)
    ).scalar_one_or_none()
    if user is None or user.status != UserStatus.approved:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not approved")
    return {"name": user.username, "admin": user.role == UserRole.admin}


@router.post("/authenticate")
def authenticate(
    body: dict,
    x_sat_internal: str = Header(default=""),
    db: Session = Depends(get_db),
):
    """Credential check used by the JupyterHub authenticator.

    Only callable by components holding the internal shared secret (the Hub
    container). Returns the Hub identity for an approved user, or 401/403.
    """
    if x_sat_internal != settings.internal_shared_secret:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad internal auth")
    username = (body or {}).get("username", "")
    password = (body or {}).get("password", "")
    user = db.execute(
        select(User).where((User.username == username) | (User.email == username))
    ).scalar_one_or_none()
    if user is None or not verify_password(password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad credentials")
    if user.status != UserStatus.approved:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"account {user.status.value}")
    return {"name": user.username, "admin": user.role == UserRole.admin}


@router.post("/verify-user")
def verify_user(
    body: dict,
    x_sat_internal: str = Header(default=""),
    db: Session = Depends(get_db),
):
    # Caller (the Hub container) must present the shared secret too.
    if x_sat_internal != settings.internal_shared_secret:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad internal auth")
    username = (body or {}).get("username", "")
    handshake = (body or {}).get("handshake", "")
    if not verify_internal_token(username, handshake):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad handshake")
    user = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
    if user is None or user.status != UserStatus.approved:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not approved")
    return {"name": user.username, "admin": user.role == UserRole.admin}
