"""Admin control plane: approve/reject/suspend users, view usage, read logs.

Admins have absolute power over the membership lifecycle. Every action is
recorded in the tamper-evident audit chain.
"""
from __future__ import annotations

import asyncio
import csv
import io

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import secrets as _secrets
from datetime import timedelta

from .. import audit, hub, kv, scheduler
from ..config import get_settings
from ..database import get_db
from ..deps import require_admin
from ..models import (
    AuditLog,
    BoostStatus,
    GpuBoostRequest,
    InviteCode,
    Node,
    NodeStatus,
    Notification,
    NotebookRun,
    User,
    UserRole,
    UserSession,
    UserStatus,
)
from ..netutil import client_ip
from ..schemas import (
    AnnounceRequest,
    ApproveRequest,
    AuditOut,
    BoostDecision,
    BoostOut,
    BulkAction,
    CreateUserRequest,
    ExpiryUpdate,
    InviteCreate,
    InviteOut,
    MaintenanceRequest,
    NodeOut,
    QuotaUpdate,
    RejectRequest,
    RoleUpdate,
    TagsUpdate,
    UserOut,
)
from ..security import hash_password
from ..timeutil import aware, utcnow

router = APIRouter(prefix="/api/admin", tags=["admin"])
settings = get_settings()

# A small allow-list of named PromQL queries the dashboard can run. Keeping it
# server-side avoids exposing arbitrary query execution and keeps the SPA simple.
METRIC_QUERIES = {
    "cpu_busy": '100 - (avg(rate(node_cpu_seconds_total{mode="idle"}[2m])) * 100)',
    "mem_used": "(1 - (sum(node_memory_MemAvailable_bytes) / sum(node_memory_MemTotal_bytes))) * 100",
    "disk_used": '(1 - (sum(node_filesystem_avail_bytes{fstype!~"tmpfs|overlay"}) / sum(node_filesystem_size_bytes{fstype!~"tmpfs|overlay"}))) * 100',
    "gpu_util": "avg(DCGM_FI_DEV_GPU_UTIL)",
    "net_rx": 'sum(rate(node_network_receive_bytes_total{device!~"lo|veth.*|docker.*"}[2m]))',
    "nodes_up": "count(up == 1)",
}


def _ip(request: Request) -> str:
    return client_ip(request)


def _ensure_not_owner(user: User) -> None:
    """The owner account is un-removable: no admin action may touch it."""
    if user.role == UserRole.owner:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "The owner account is protected and cannot be modified.")


def _hide_owner(requester: User):
    """Owner is practically invisible: every admin listing excludes owner rows
    unless the requester *is* the owner (who manages everything)."""
    return requester.role != UserRole.owner


def _gpu_hours_used(db: Session, user_id: str) -> float:
    return scheduler.gpu_hours_used(db, user_id)


@router.get("/users", response_model=list[UserOut])
def list_users(
    status_filter: str | None = Query(default=None, alias="status"),
    q: str | None = Query(default=None, description="search username/email/name"),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    stmt = select(User).order_by(User.created_at.desc())
    if _hide_owner(admin):
        stmt = stmt.where(User.role != UserRole.owner)   # owner stays invisible
    if status_filter:
        try:
            stmt = stmt.where(User.status == UserStatus(status_filter))
        except ValueError:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown status filter")
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(
            func.lower(User.username).like(like)
            | func.lower(User.email).like(like)
            | func.lower(User.full_name).like(like)
        )
    return list(db.execute(stmt).scalars())


@router.get("/users/pending", response_model=list[UserOut])
def pending(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return list(
        db.execute(
            select(User).where(User.status == UserStatus.pending).order_by(User.created_at)
        ).scalars()
    )


@router.post("/users/approve", response_model=UserOut)
async def approve(
    payload: ApproveRequest,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = db.get(User, payload.user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    _ensure_not_owner(user)
    if payload.role == UserRole.owner.value:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "The owner role cannot be granted.")
    user.status = UserStatus.approved
    user.role = UserRole(payload.role) if payload.role in (r.value for r in UserRole) else UserRole.user
    user.approved_by = admin.id
    from datetime import datetime, timezone
    user.approved_at = datetime.now(timezone.utc)
    db.commit()

    # Mirror into JupyterHub so the user can spawn a notebook.
    try:
        await hub.ensure_user(user.username, admin=(user.role == UserRole.admin))
    except Exception:  # hub may be momentarily down; approval still stands
        pass

    audit.record(db, action="admin.approve_user", actor_id=admin.id, actor_label=admin.username,
                 target=user.username, ip=_ip(request),
                 detail={"role": user.role.value})
    return user


@router.post("/users/reject", response_model=UserOut)
def reject(
    payload: RejectRequest,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = db.get(User, payload.user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    _ensure_not_owner(user)
    user.status = UserStatus.rejected
    db.commit()
    audit.record(db, action="admin.reject_user", actor_id=admin.id, actor_label=admin.username,
                 target=user.username, ip=_ip(request), detail={"reason": payload.reason})
    return user


@router.post("/users/{user_id}/suspend", response_model=UserOut)
async def suspend(
    user_id: str,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    _ensure_not_owner(user)
    if user.id == admin.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot suspend yourself")
    user.status = UserStatus.suspended
    # Revoke all live sessions immediately — kick them off.
    for s in db.execute(select(UserSession).where(UserSession.user_id == user.id)).scalars():
        s.revoked = True
    db.commit()
    try:
        await hub.delete_user(user.username)  # stop & remove their running server
    except Exception:
        pass
    audit.record(db, action="admin.suspend_user", actor_id=admin.id, actor_label=admin.username,
                 target=user.username, ip=_ip(request))
    return user


@router.post("/users/{user_id}/reinstate", response_model=UserOut)
async def reinstate(
    user_id: str,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    _ensure_not_owner(user)
    user.status = UserStatus.approved
    db.commit()
    try:
        await hub.ensure_user(user.username)
    except Exception:
        pass
    audit.record(db, action="admin.reinstate_user", actor_id=admin.id, actor_label=admin.username,
                 target=user.username, ip=_ip(request))
    return user


@router.post("/users/{user_id}/reset-2fa", response_model=UserOut)
def reset_2fa(user_id: str, request: Request,
              admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Recovery: clear a user's TOTP so they can re-enrol (lost authenticator)."""
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    _ensure_not_owner(user)
    user.totp_enabled = False
    user.totp_secret = None
    db.commit()
    audit.record(db, action="admin.reset_2fa", actor_id=admin.id, actor_label=admin.username,
                 target=user.username, ip=_ip(request))
    return user


@router.post("/users/{user_id}/reset-password")
def reset_password(user_id: str, request: Request,
                   admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Recovery: set a random temporary password the admin relays to the user.

    The user must change it on next login (must_change_password) and all their
    sessions are revoked. Returns the temp password ONCE."""
    import secrets as _secrets

    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    _ensure_not_owner(user)
    temp = _secrets.token_urlsafe(12)
    user.password_hash = hash_password(temp)
    user.must_change_password = True
    user.failed_logins = 0
    user.locked_until = None
    for s in db.execute(select(UserSession).where(UserSession.user_id == user.id)).scalars():
        s.revoked = True
    db.commit()
    audit.record(db, action="admin.reset_password", actor_id=admin.id, actor_label=admin.username,
                 target=user.username, ip=_ip(request))
    return {"username": user.username, "temporary_password": temp,
            "note": "Relay securely; the user must change it on next login."}


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(user_id: str, request: Request,
                      admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Permanently remove a user (and their Hub account/server)."""
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    _ensure_not_owner(user)
    if user.id == admin.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot delete yourself")
    username = user.username
    try:
        await hub.delete_user(username)
    except Exception:
        pass
    db.delete(user)   # sessions cascade-delete
    db.commit()
    audit.record(db, action="admin.delete_user", actor_id=admin.id, actor_label=admin.username,
                 target=username, ip=_ip(request))
    return None


@router.post("/users/{user_id}/role", response_model=UserOut)
async def set_role(user_id: str, payload: RoleUpdate, request: Request,
                   admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Appoint or demote an admin (owner role can never be granted or removed)."""
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    _ensure_not_owner(user)
    if user.id == admin.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You can't change your own role")
    user.role = UserRole(payload.role)
    db.commit()
    try:
        await hub.ensure_user(user.username, admin=(user.role == UserRole.admin))
    except Exception:
        pass
    audit.record(db, action="admin.set_role", actor_id=admin.id, actor_label=admin.username,
                 target=user.username, ip=_ip(request), detail={"role": user.role.value})
    return user


@router.post("/users", response_model=UserOut, status_code=201)
async def create_user(payload: CreateUserRequest, request: Request,
                      admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Create + auto-approve an account (optionally an admin) directly from the web."""
    dup = db.execute(select(User).where(
        (User.username == payload.username) | (User.email == payload.email)
    )).scalars().first()
    if dup:
        raise HTTPException(status.HTTP_409_CONFLICT, "Username or email already in use")
    user = User(
        email=payload.email, username=payload.username, full_name=payload.full_name,
        password_hash=hash_password(payload.password), role=UserRole(payload.role),
        status=UserStatus.approved, must_change_password=True,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Username or email already in use")
    try:
        await hub.ensure_user(user.username, admin=(user.role == UserRole.admin))
    except Exception:
        pass
    audit.record(db, action="admin.create_user", actor_id=admin.id, actor_label=admin.username,
                 target=user.username, ip=_ip(request), detail={"role": user.role.value})
    return user


@router.post("/users/bulk")
async def bulk_users(payload: BulkAction, request: Request,
                     admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Apply one action to many users at once (owner + self always skipped)."""
    done, skipped, teardown = 0, 0, []
    for uid in payload.user_ids:
        user = db.get(User, uid)
        if user is None or user.role == UserRole.owner or user.id == admin.id:
            skipped += 1
            continue
        a = payload.action
        if a == "approve":
            user.status = UserStatus.approved
        elif a == "reject":
            user.status = UserStatus.rejected
        elif a == "reinstate":
            user.status = UserStatus.approved
        elif a == "suspend":
            user.status = UserStatus.suspended
            for s in db.execute(select(UserSession).where(UserSession.user_id == user.id)).scalars():
                s.revoked = True
            teardown.append(user.username)
        elif a == "delete":
            teardown.append(user.username)
            db.delete(user)
        done += 1
    db.commit()
    if payload.action in ("suspend", "delete"):
        for uname in teardown:
            try:
                await hub.delete_user(uname)
            except Exception:
                pass
    audit.record(db, action=f"admin.bulk_{payload.action}", actor_id=admin.id,
                 actor_label=admin.username, ip=_ip(request),
                 detail={"count": done, "skipped": skipped})
    return {"done": done, "skipped": skipped}


@router.get("/nodes", response_model=list[NodeOut])
def nodes(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """List cluster nodes. A node whose heartbeat is stale is reported offline
    (derived live from last_heartbeat — fixes 'dead node still shows online')."""
    cutoff_age = settings.node_offline_seconds
    out = []
    for n in db.execute(select(Node).order_by(Node.role.desc(), Node.hostname)).scalars():
        hb = aware(n.last_heartbeat)
        if hb is None or (utcnow() - hb).total_seconds() > cutoff_age:
            n.status = NodeStatus.offline
        out.append(n)
    return out


@router.post("/nodes/{node_id}/drain", response_model=NodeOut)
def drain_node(node_id: str, request: Request,
               admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Maintenance mode: stop scheduling new notebooks onto this node so it can be
    rebooted/serviced. Running notebooks are left alone (drain, don't kill)."""
    node = db.get(Node, node_id)
    if node is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Node not found")
    node.status = NodeStatus.draining
    db.commit()
    db.refresh(node)
    audit.record(db, action="admin.node_drain", actor_id=admin.id, actor_label=admin.username,
                 target=node.hostname, ip=_ip(request))
    return node


@router.post("/nodes/{node_id}/activate", response_model=NodeOut)
def activate_node(node_id: str, request: Request,
                  admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Return a drained node to the scheduling pool."""
    node = db.get(Node, node_id)
    if node is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Node not found")
    node.status = NodeStatus.online
    db.commit()
    db.refresh(node)
    audit.record(db, action="admin.node_activate", actor_id=admin.id, actor_label=admin.username,
                 target=node.hostname, ip=_ip(request))
    return node


# ----------------------------------------------------------- GPU boost review ---
@router.get("/boosts", response_model=list[BoostOut])
def list_boosts(status_filter: str = Query(default="pending", alias="status"),
                admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    stmt = select(GpuBoostRequest).order_by(GpuBoostRequest.created_at.desc())
    if status_filter and status_filter != "all":
        try:
            stmt = stmt.where(GpuBoostRequest.status == BoostStatus(status_filter))
        except ValueError:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown boost status")
    return list(db.execute(stmt).scalars())


@router.post("/boosts/{boost_id}/approve", response_model=BoostOut)
def approve_boost(boost_id: str, payload: BoostDecision, request: Request,
                  admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    req = db.get(GpuBoostRequest, boost_id)
    if req is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Boost request not found")
    if req.status != BoostStatus.pending:
        raise HTTPException(status.HTTP_409_CONFLICT, "Request already decided")
    if payload.gpus:
        req.gpus = payload.gpus
    req.status = BoostStatus.approved
    req.decided_at = utcnow()
    req.decided_by = admin.id
    scheduler.notify(db, req.user_id, "boost",
                     f"Your GPU boost was approved for {req.gpus} GPU node(s). "
                     "Launch (or relaunch) your notebook to use it — good for one session.")
    db.commit()
    db.refresh(req)
    audit.record(db, action="admin.boost_approve", actor_id=admin.id, actor_label=admin.username,
                 target=req.username, ip=_ip(request), detail={"gpus": req.gpus})
    return req


@router.post("/boosts/{boost_id}/deny", response_model=BoostOut)
def deny_boost(boost_id: str, payload: BoostDecision, request: Request,
               admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    req = db.get(GpuBoostRequest, boost_id)
    if req is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Boost request not found")
    if req.status != BoostStatus.pending:
        raise HTTPException(status.HTTP_409_CONFLICT, "Request already decided")
    req.status = BoostStatus.denied
    req.decided_at = utcnow()
    req.decided_by = admin.id
    scheduler.notify(db, req.user_id, "warning",
                     "Your GPU boost request was declined" +
                     (f": {payload.reason}" if payload.reason else "."))
    db.commit()
    db.refresh(req)
    audit.record(db, action="admin.boost_deny", actor_id=admin.id, actor_label=admin.username,
                 target=req.username, ip=_ip(request))
    return req


@router.get("/sessions/active")
async def active_notebooks(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    try:
        active = await hub.list_active()
    except Exception:
        return []
    if _hide_owner(admin):
        owners = {u.username for u in db.execute(
            select(User).where(User.role == UserRole.owner)).scalars()}
        active = [a for a in active if a.get("username") not in owners]
    return active


@router.get("/audit", response_model=list[AuditOut])
def audit_log(
    limit: int = Query(default=100, le=1000),
    offset: int = 0,
    q: str | None = Query(default=None, description="search actor/action/target"),
    username: str | None = Query(default=None, description="filter by actor username"),
    action: str | None = Query(default=None, description="filter by action prefix"),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Total audit log with server-side search/filter (owner activity never
    appears — it isn't recorded)."""
    stmt = select(AuditLog).order_by(AuditLog.id.desc())
    if username:
        stmt = stmt.where(func.lower(AuditLog.actor_label) == username.lower())
    if action:
        stmt = stmt.where(AuditLog.action.like(f"{action}%"))
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(
            func.lower(AuditLog.actor_label).like(like)
            | func.lower(AuditLog.action).like(like)
            | func.lower(AuditLog.target).like(like)
        )
    return list(db.execute(stmt.limit(limit).offset(offset)).scalars())


@router.get("/users/{user_id}/logs", response_model=list[AuditOut])
def user_logs(user_id: str, limit: int = Query(default=200, le=1000),
              admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Per-user activity: everything this user did, plus admin actions targeting them."""
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    _ensure_not_owner(user)  # owner has no logs anyway, but keep it invisible
    stmt = select(AuditLog).where(
        (AuditLog.actor_id == user_id) | (AuditLog.target == user.username)
    ).order_by(AuditLog.id.desc()).limit(limit)
    return list(db.execute(stmt).scalars())


@router.get("/audit/verify")
def audit_verify(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    ok, bad = audit.verify_chain(db)
    return {"intact": ok, "first_tampered_id": bad}


@router.get("/audit/export.csv")
def audit_export(request: Request, limit: int = Query(default=10000, le=100000),
                 admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Download the audit trail as CSV (compliance / offline review)."""
    rows = list(db.execute(
        select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)
    ).scalars())
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "timestamp", "actor", "action", "target", "ip", "detail"])
    for a in rows:
        ts = aware(a.timestamp)
        w.writerow([a.id, ts.isoformat() if ts else "", a.actor_label, a.action,
                    a.target, a.ip, a.detail])
    audit.record(db, action="admin.audit_export", actor_id=admin.id,
                 actor_label=admin.username, ip=_ip(request), detail={"rows": len(rows)})
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=satyameba-audit.csv"},
    )


@router.get("/metrics/live")
async def metrics_live(admin: User = Depends(require_admin)):
    """Pull live cluster numbers straight from Prometheus for the dashboard.

    Returns a flat {name: value|null} map for the allow-listed queries so the
    admin Overview can show CPU/RAM/disk/GPU/network on the go.
    """
    async def _one(client, name, q):
        try:
            r = await client.get(f"{settings.prometheus_url}/api/v1/query", params={"query": q})
            result = r.json().get("data", {}).get("result", [])
            return name, (float(result[0]["value"][1]) if result else None)
        except Exception:
            return name, None

    try:
        async with httpx.AsyncClient(timeout=2) as client:
            pairs = await asyncio.gather(
                *(_one(client, name, q) for name, q in METRIC_QUERIES.items())
            )
        return dict(pairs)
    except Exception:
        return {k: None for k in METRIC_QUERIES}


# ------------------------------------------------------------ admin-ease ------
@router.post("/invites", response_model=InviteOut, status_code=201)
def create_invite(payload: InviteCreate, request: Request,
                  admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Generate an invite code; users who register with it are auto-approved."""
    exp = utcnow() + timedelta(days=payload.expires_in_days) if payload.expires_in_days else None
    inv = InviteCode(code=_secrets.token_urlsafe(9), role=UserRole(payload.role),
                     max_uses=payload.max_uses, expires_at=exp, created_by=admin.id)
    db.add(inv)
    db.commit()
    db.refresh(inv)
    audit.record(db, action="admin.create_invite", actor_id=admin.id, actor_label=admin.username,
                 ip=_ip(request), detail={"role": payload.role, "max_uses": payload.max_uses})
    return inv


@router.get("/invites", response_model=list[InviteOut])
def list_invites(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return list(db.execute(select(InviteCode).order_by(InviteCode.created_at.desc())).scalars())


@router.post("/invites/{code}/revoke")
def revoke_invite(code: str, request: Request,
                  admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    inv = db.get(InviteCode, code)
    if inv is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invite not found")
    inv.active = False
    db.commit()
    audit.record(db, action="admin.revoke_invite", actor_id=admin.id, actor_label=admin.username,
                 target=code, ip=_ip(request))
    return {"ok": True}


@router.post("/users/{user_id}/expiry", response_model=UserOut)
def set_expiry(user_id: str, payload: ExpiryUpdate, request: Request,
               admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Set/clear an account expiry — expired users are auto-suspended at login."""
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    _ensure_not_owner(user)
    if payload.clear:
        user.expires_at = None
    elif payload.days:
        user.expires_at = utcnow() + timedelta(days=payload.days)
    db.commit()
    audit.record(db, action="admin.set_expiry", actor_id=admin.id, actor_label=admin.username,
                 target=user.username, ip=_ip(request),
                 detail={"expires_at": user.expires_at.isoformat() if user.expires_at else None})
    return user


@router.post("/users/{user_id}/quota", response_model=UserOut)
def set_quota(user_id: str, payload: QuotaUpdate, request: Request,
              admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Set/clear a per-user GPU-hours cap (enforced at launch)."""
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    _ensure_not_owner(user)
    user.gpu_hours_limit = None if payload.clear else payload.gpu_hours_limit
    db.commit()
    audit.record(db, action="admin.set_quota", actor_id=admin.id, actor_label=admin.username,
                 target=user.username, ip=_ip(request),
                 detail={"gpu_hours_limit": user.gpu_hours_limit})
    return user


@router.post("/users/{user_id}/tags", response_model=UserOut)
def set_tags(user_id: str, payload: TagsUpdate, request: Request,
             admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Label a user (e.g. Class-A) for grouping + bulk actions."""
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    _ensure_not_owner(user)
    user.tags = [t.strip()[:32] for t in payload.tags if t.strip()][:20]
    db.commit()
    audit.record(db, action="admin.set_tags", actor_id=admin.id, actor_label=admin.username,
                 target=user.username, ip=_ip(request), detail={"tags": user.tags})
    return user


@router.get("/users/{user_id}/usage")
def user_usage(user_id: str, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    active = db.execute(select(func.count()).select_from(NotebookRun).where(
        NotebookRun.user_id == user_id, NotebookRun.status == "active")).scalar_one()
    return {
        "gpu_hours_used": _gpu_hours_used(db, user_id),
        "gpu_hours_limit": user.gpu_hours_limit,
        "active_runs": active,
        "expires_at": user.expires_at,
        "tags": user.tags,
    }


@router.get("/attention")
def attention(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """One-glance panel: what needs the admin's eyes right now."""
    pending = db.execute(select(func.count()).select_from(User).where(
        User.status == UserStatus.pending, User.role != UserRole.owner)).scalar_one()
    boosts = db.execute(select(func.count()).select_from(GpuBoostRequest).where(
        GpuBoostRequest.status == BoostStatus.pending)).scalar_one()
    locked = db.execute(select(func.count()).select_from(User).where(
        User.role != UserRole.owner, User.locked_until.is_not(None))).scalar_one()
    cutoff = settings.node_offline_seconds
    offline = 0
    for n in db.execute(select(Node)).scalars():
        hb = aware(n.last_heartbeat)
        if hb is None or (utcnow() - hb).total_seconds() > cutoff:
            offline += 1
    return {"pending_users": pending, "pending_boosts": boosts,
            "locked_users": locked, "offline_nodes": offline,
            "maintenance": kv.is_maintenance(db)}


@router.post("/announce")
def announce(payload: AnnounceRequest, request: Request,
             admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Broadcast a notice to every active user's notification bell."""
    sent = 0
    for u in db.execute(select(User).where(
        User.status == UserStatus.approved, User.role != UserRole.owner)).scalars():
        db.add(Notification(user_id=u.id, kind=payload.kind, message=payload.message[:512]))
        sent += 1
    db.commit()
    audit.record(db, action="admin.announce", actor_id=admin.id, actor_label=admin.username,
                 ip=_ip(request), detail={"sent": sent})
    return {"sent": sent}


@router.get("/maintenance")
def get_maintenance(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return {"on": kv.is_maintenance(db), "message": kv.get_setting(db, kv.MAINTENANCE_MSG, "")}


@router.post("/maintenance")
def set_maintenance(payload: MaintenanceRequest, request: Request,
                    admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Toggle maintenance mode — blocks new notebook launches + shows a banner."""
    kv.set_setting(db, kv.MAINTENANCE, "1" if payload.on else "0")
    kv.set_setting(db, kv.MAINTENANCE_MSG, payload.message)
    db.commit()
    audit.record(db, action="admin.maintenance", actor_id=admin.id, actor_label=admin.username,
                 ip=_ip(request), detail={"on": payload.on})
    return {"on": payload.on, "message": payload.message}


@router.get("/stats")
def stats(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    def _count(s):
        stmt = select(func.count()).select_from(User).where(User.status == s)
        if _hide_owner(admin):
            stmt = stmt.where(User.role != UserRole.owner)
        return db.execute(stmt).scalar_one()

    counts = {s.value: _count(s) for s in UserStatus}
    node_count = db.execute(select(func.count()).select_from(Node)).scalar_one()
    return {"users": counts, "nodes": node_count}
