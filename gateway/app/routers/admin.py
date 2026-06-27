"""Admin control plane: approve/reject/suspend users, view usage, read logs.

Admins have absolute power over the membership lifecycle. Every action is
recorded in the tamper-evident audit chain.
"""
from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit, hub
from ..config import get_settings
from ..database import get_db
from ..deps import require_admin
from ..models import AuditLog, Node, User, UserRole, UserSession, UserStatus
from ..schemas import ApproveRequest, AuditOut, NodeOut, RejectRequest, UserOut

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
    fwd = request.headers.get("x-forwarded-for")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "")


@router.get("/users", response_model=list[UserOut])
def list_users(
    status_filter: str | None = Query(default=None, alias="status"),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    stmt = select(User).order_by(User.created_at.desc())
    if status_filter:
        try:
            stmt = stmt.where(User.status == UserStatus(status_filter))
        except ValueError:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown status filter")
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
    user.status = UserStatus.approved
    db.commit()
    try:
        await hub.ensure_user(user.username)
    except Exception:
        pass
    audit.record(db, action="admin.reinstate_user", actor_id=admin.id, actor_label=admin.username,
                 target=user.username, ip=_ip(request))
    return user


@router.get("/nodes", response_model=list[NodeOut])
def nodes(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return list(db.execute(select(Node).order_by(Node.role.desc(), Node.hostname)).scalars())


@router.get("/sessions/active")
async def active_notebooks(admin: User = Depends(require_admin)):
    try:
        return await hub.list_active()
    except Exception:
        return []


@router.get("/audit", response_model=list[AuditOut])
def audit_log(
    limit: int = Query(default=100, le=1000),
    offset: int = 0,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return list(
        db.execute(
            select(AuditLog).order_by(AuditLog.id.desc()).limit(limit).offset(offset)
        ).scalars()
    )


@router.get("/audit/verify")
def audit_verify(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    ok, bad = audit.verify_chain(db)
    return {"intact": ok, "first_tampered_id": bad}


@router.get("/metrics/live")
async def metrics_live(admin: User = Depends(require_admin)):
    """Pull live cluster numbers straight from Prometheus for the dashboard.

    Returns a flat {name: value|null} map for the allow-listed queries so the
    admin Overview can show CPU/RAM/disk/GPU/network on the go.
    """
    out: dict[str, float | None] = {}
    try:
        async with httpx.AsyncClient(timeout=4) as client:
            for name, q in METRIC_QUERIES.items():
                try:
                    r = await client.get(
                        f"{settings.prometheus_url}/api/v1/query", params={"query": q}
                    )
                    result = r.json().get("data", {}).get("result", [])
                    out[name] = float(result[0]["value"][1]) if result else None
                except Exception:
                    out[name] = None
    except Exception:
        out = {k: None for k in METRIC_QUERIES}
    return out


@router.get("/stats")
def stats(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    counts = {
        s.value: db.execute(
            select(func.count()).select_from(User).where(User.status == s)
        ).scalar_one()
        for s in UserStatus
    }
    node_count = db.execute(select(func.count()).select_from(Node)).scalar_one()
    return {"users": counts, "nodes": node_count}
