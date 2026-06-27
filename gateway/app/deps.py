"""FastAPI dependencies: extract & validate the current user/session."""
from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .database import get_db
from .models import User, UserRole, UserSession, UserStatus
from .security import decode_token
from .timeutil import aware, utcnow

settings = get_settings()

# While a forced password change is pending, only these paths are reachable.
_PW_CHANGE_ALLOWED = (
    "/api/auth/change-password",
    "/api/auth/me",
    "/api/auth/logout",
)


def _bearer(request: Request) -> str:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    return header.split(" ", 1)[1].strip()


def get_current_session(request: Request, db: Session = Depends(get_db)) -> tuple[User, UserSession]:
    token = _bearer(request)
    try:
        payload = decode_token(token)
    except Exception:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    if payload.get("type") != "access":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong token type")

    session = db.execute(
        select(UserSession).where(UserSession.jti == payload["jti"])
    ).scalar_one_or_none()
    if session is None or session.revoked:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session revoked")
    if aware(session.expires_at) < utcnow():
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired")

    user = db.get(User, payload["sub"])
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown user")
    if user.status != UserStatus.approved:
        # An admin may have suspended the account mid-session.
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Account is {user.status.value}")

    # Enforce a pending password change: lock the user out of everything except
    # changing it (the SPA routes them to the change-password form).
    if user.must_change_password and request.url.path not in _PW_CHANGE_ALLOWED:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "password_change_required")

    return user, session


def get_current_user(pair: tuple[User, UserSession] = Depends(get_current_session)) -> User:
    return pair[0]


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role not in (UserRole.admin, UserRole.owner):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Administrator privileges required")
    # Optionally require admins to have enrolled TOTP before any privileged action.
    # The owner is exempt (their break-glass path is the out-of-band tunnel).
    if settings.require_admin_2fa and user.role != UserRole.owner and not user.totp_enabled:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "admin_2fa_required")
    return user
