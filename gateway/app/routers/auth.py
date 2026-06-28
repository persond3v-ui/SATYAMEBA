"""Registration, login, refresh, logout."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit, hub
from ..config import get_settings
from ..database import get_db
from ..deps import get_current_session, get_current_user
from ..models import AuditLog, InviteCode, User, UserRole, UserSession, UserStatus
from ..schemas import (
    AuditOut,
    ChangePasswordRequest,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    TwoFACodeRequest,
    TwoFASetupResponse,
    UserOut,
)
from ..netutil import client_ip
from ..security import (
    create_access_token,
    decode_token,
    decrypt_secret,
    encrypt_secret,
    hash_password,
    new_jti,
    new_signing_key,
    new_totp_secret,
    totp_uri,
    verify_password,
    verify_totp,
)
from ..timeutil import aware, utcnow

router = APIRouter(prefix="/api/auth", tags=["auth"])
settings = get_settings()

MAX_FAILED = 5
LOCK_MINUTES = 15


def _client_ip(request: Request) -> str:
    return client_ip(request)


def _register_failure(db: Session, user: User, request: Request) -> None:
    """Count a failed auth attempt (bad password OR bad OTP) and lock the account
    after too many — so the second factor is brute-force protected too."""
    now = datetime.now(timezone.utc)
    user.failed_logins += 1
    if user.failed_logins >= MAX_FAILED:
        user.locked_until = now + timedelta(minutes=LOCK_MINUTES)
        user.failed_logins = 0
        audit.record(db, action="user.locked", actor_id=user.id,
                     actor_label=user.username, ip=_client_ip(request))
    db.commit()


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

    # A valid invite code auto-approves the account (skips the manual queue).
    role, status_, invite = UserRole.user, UserStatus.pending, None
    if payload.invite_code:
        invite = db.get(InviteCode, payload.invite_code)
        exp_ok = invite is None or invite.expires_at is None or aware(invite.expires_at) > utcnow()
        if invite and invite.active and invite.uses < invite.max_uses and exp_ok:
            role, status_ = invite.role, UserStatus.approved
        else:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invite code is invalid or used up")

    user = User(
        email=payload.email,
        username=payload.username,
        full_name=payload.full_name,
        password_hash=hash_password(payload.password),
        role=role,
        status=status_,
    )
    db.add(user)
    if invite is not None:
        invite.uses += 1
        if invite.uses >= invite.max_uses:
            invite.active = False
    db.commit()
    db.refresh(user)
    # Invited (auto-approved) users are mirrored into the Hub on first launch.
    audit.record(
        db,
        action="user.register",
        actor_id=user.id,
        actor_label=user.username,
        target=user.email,
        ip=_client_ip(request),
        user_agent=request.headers.get("user-agent", ""),
        detail={"invited": bool(invite)},
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
        _register_failure(db, user, request)
        raise generic

    if user.status == UserStatus.pending:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account pending admin approval")
    if user.status in (UserStatus.rejected, UserStatus.suspended):
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Account {user.status.value}")

    # Second factor (TOTP) when enabled for this account.
    if user.totp_enabled:
        if not payload.otp:
            # Distinct code so the SPA can prompt for the 6-digit token.
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "otp_required")
        if not verify_totp(decrypt_secret(user.totp_secret), payload.otp):
            _register_failure(db, user, request)   # 2FA brute-force is locked too
            raise generic

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
async def logout(request: Request, pair=Depends(get_current_session), db: Session = Depends(get_db)):
    user, session = pair
    session.revoked = True
    db.commit()
    # The browser session is over — tear down the user's notebook server too.
    try:
        await hub.stop_server(user.username)
    except Exception:
        pass
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
    user.must_change_password = False
    # Invalidate every other session; keep the one making the change.
    for s in db.execute(
        select(UserSession).where(UserSession.user_id == user.id, UserSession.id != current.id)
    ).scalars():
        s.revoked = True
    db.commit()
    audit.record(db, action="user.change_password", actor_id=user.id,
                 actor_label=user.username, ip=_client_ip(request))
    return None


# --------------------------------------------------------------------------- #
# Two-factor (TOTP) enrolment
# --------------------------------------------------------------------------- #
@router.post("/2fa/setup", response_model=TwoFASetupResponse)
def twofa_setup(pair=Depends(get_current_session), db: Session = Depends(get_db)):
    """Generate a TOTP secret + QR. 2FA is not active until /2fa/enable confirms a code."""
    import base64
    import io

    import segno

    user, _ = pair
    secret = new_totp_secret()
    user.totp_secret = encrypt_secret(secret)   # stored encrypted at rest
    user.totp_enabled = False  # stays off until a code is verified
    db.commit()
    uri = totp_uri(secret, user.username)
    buff = io.BytesIO()
    segno.make(uri).save(buff, kind="png", scale=4)
    data_uri = "data:image/png;base64," + base64.b64encode(buff.getvalue()).decode()
    return TwoFASetupResponse(secret=secret, otpauth_uri=uri, qr_png_data_uri=data_uri)


@router.post("/2fa/enable", status_code=204)
def twofa_enable(payload: TwoFACodeRequest, request: Request,
                 pair=Depends(get_current_session), db: Session = Depends(get_db)):
    user, _ = pair
    if not user.totp_secret or not verify_totp(decrypt_secret(user.totp_secret), payload.code):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid code — try again")
    user.totp_enabled = True
    db.commit()
    audit.record(db, action="user.2fa_enable", actor_id=user.id,
                 actor_label=user.username, ip=_client_ip(request))
    return None


@router.post("/2fa/disable", status_code=204)
def twofa_disable(payload: TwoFACodeRequest, request: Request,
                  pair=Depends(get_current_session), db: Session = Depends(get_db)):
    user, _ = pair
    if not user.totp_enabled or not verify_totp(decrypt_secret(user.totp_secret), payload.code):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid code")
    user.totp_enabled = False
    user.totp_secret = None
    db.commit()
    audit.record(db, action="user.2fa_disable", actor_id=user.id,
                 actor_label=user.username, ip=_client_ip(request))
    return None


@router.get("/me", response_model=UserOut)
def me(pair=Depends(get_current_session)):
    return pair[0]


@router.get("/me/logs", response_model=list[AuditOut])
def my_logs(
    limit: int = Query(default=200, le=1000),
    q: str | None = Query(default=None, description="search action/target"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """A user's own activity log (their actions only)."""
    stmt = select(AuditLog).where(AuditLog.actor_id == user.id).order_by(AuditLog.id.desc())
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(
            func.lower(AuditLog.action).like(like) | func.lower(AuditLog.target).like(like)
        )
    return list(db.execute(stmt.limit(limit)).scalars())
