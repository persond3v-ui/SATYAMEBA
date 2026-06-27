"""Registration, login, refresh, logout."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..config import get_settings
from ..database import get_db
from ..deps import get_current_session
from ..models import User, UserRole, UserSession, UserStatus
from ..schemas import (
    ChangePasswordRequest,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserOut,
)
from ..security import (
    create_access_token,
    decode_token,
    hash_password,
    new_jti,
    new_signing_key,
    verify_password,
)
from ..timeutil import aware

router = APIRouter(prefix="/api/auth", tags=["auth"])
settings = get_settings()

MAX_FAILED = 5
LOCK_MINUTES = 15


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _issue_session(db: Session, user: User, request: Request) -> TokenResponse:
    jti = new_jti()
    signing_key = new_signing_key()
    now = datetime.now(timezone.utc)
    session = UserSession(
        user_id=user.id,
        jti=jti,
        signing_key=signing_key,
        issued_at=now,
        expires_at=now + timedelta(seconds=settings.refresh_token_ttl_seconds),
        ip=_client_ip(request),
        user_agent=request.headers.get("user-agent", "")[:512],
    )
    db.add(session)
    user.last_login_at = now
    user.failed_logins = 0
    db.commit()

    access = create_access_token(sub=user.id, role=user.role.value, jti=jti)
    # The refresh token is itself a signed JWT bound to the same jti.
    refresh = create_access_token(
        sub=user.id, role=user.role.value, jti=jti, extra={"type": "refresh"}
    )
    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        expires_in=settings.access_token_ttl_seconds,
        signing_key=signing_key,
    )


@router.post("/register", response_model=UserOut, status_code=201)
def register(payload: RegisterRequest, request: Request, db: Session = Depends(get_db)):
    exists = db.execute(
        select(User).where(
            (User.email == payload.email) | (User.username == payload.username)
        )
    ).scalar_one_or_none()
    if exists:
        # Do not reveal which field collided (user enumeration, OWASP A07).
        raise HTTPException(status.HTTP_409_CONFLICT, "Could not register with those details")

    user = User(
        email=payload.email,
        username=payload.username,
        full_name=payload.full_name,
        password_hash=hash_password(payload.password),
        role=UserRole.user,
        status=UserStatus.pending,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    audit.record(
        db,
        action="user.register",
        actor_id=user.id,
        actor_label=user.username,
        target=user.email,
        ip=_client_ip(request),
        user_agent=request.headers.get("user-agent", ""),
    )
    return user


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    user = db.execute(
        select(User).where(
            (User.username == payload.username) | (User.email == payload.username)
        )
    ).scalar_one_or_none()

    now = datetime.now(timezone.utc)
    generic = HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")

    if user is None:
        # Run a dummy verify to keep timing flat against enumeration.
        verify_password(payload.password, "$2b$12$" + "x" * 53)
        raise generic

    if user.locked_until and aware(user.locked_until) > now:
        raise HTTPException(status.HTTP_423_LOCKED, "Account temporarily locked. Try later.")

    if not verify_password(payload.password, user.password_hash):
        user.failed_logins += 1
        if user.failed_logins >= MAX_FAILED:
            user.locked_until = now + timedelta(minutes=LOCK_MINUTES)
            user.failed_logins = 0
            audit.record(db, action="user.locked", actor_id=user.id,
                         actor_label=user.username, ip=_client_ip(request))
        db.commit()
        raise generic

    if user.status == UserStatus.pending:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account pending admin approval")
    if user.status in (UserStatus.rejected, UserStatus.suspended):
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Account {user.status.value}")

    tokens = _issue_session(db, user, request)
    audit.record(db, action="user.login", actor_id=user.id, actor_label=user.username,
                 ip=_client_ip(request), user_agent=request.headers.get("user-agent", ""))
    return tokens


@router.post("/refresh", response_model=TokenResponse)
def refresh(payload: RefreshRequest, request: Request, db: Session = Depends(get_db)):
    try:
        claims = decode_token(payload.refresh_token)
    except Exception:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh token")
    if claims.get("type") != "refresh":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not a refresh token")

    session = db.execute(
        select(UserSession).where(UserSession.jti == claims["jti"])
    ).scalar_one_or_none()
    if session is None or session.revoked or aware(session.expires_at) < datetime.now(timezone.utc):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired")

    user = db.get(User, claims["sub"])
    if user is None or user.status != UserStatus.approved:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account not active")

    # Rotate: revoke old session, mint a new one (refresh-token rotation).
    session.revoked = True
    db.commit()
    return _issue_session(db, user, request)


@router.post("/logout", status_code=204)
def logout(request: Request, pair=Depends(get_current_session), db: Session = Depends(get_db)):
    user, session = pair
    session.revoked = True
    db.commit()
    audit.record(db, action="user.logout", actor_id=user.id, actor_label=user.username,
                 ip=_client_ip(request))
    return None


@router.post("/change-password", status_code=204)
def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    pair=Depends(get_current_session),
    db: Session = Depends(get_db),
):
    user, current = pair
    if not verify_password(payload.old_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect")
    user.password_hash = hash_password(payload.new_password)
    # Invalidate every other session; keep the one making the change.
    for s in db.execute(
        select(UserSession).where(UserSession.user_id == user.id, UserSession.id != current.id)
    ).scalars():
        s.revoked = True
    db.commit()
    audit.record(db, action="user.change_password", actor_id=user.id,
                 actor_label=user.username, ip=_client_ip(request))
    return None


@router.get("/me", response_model=UserOut)
def me(pair=Depends(get_current_session)):
    return pair[0]
