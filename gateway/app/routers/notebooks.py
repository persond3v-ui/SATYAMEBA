"""User-facing notebook lifecycle + dynamic GPU scheduling.

The gateway brokers all Hub calls (the SPA never holds Hub admin credentials)
and, crucially, *decides placement itself* (see ``scheduler.py``) so it can give
each user a whole node when the cluster is quiet and transparently fall back to
concurrent GPU sharing when it's busy. Launch flow with single sign-on:

  1. SPA POSTs /launch with a desired resource ``profile``.
  2. The scheduler picks a node + sharing mode (and folds in any admin-approved
     GPU boost), the gateway tells the Hub to start the server with those
     options, mints a single-use SSO token and returns an ``/hub/sso-login`` URL.
  3. The SPA opens that URL; the Hub redeems the token and lands on JupyterLab.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select

from .. import audit, hub, kv, scheduler
from ..config import get_settings
from ..database import get_db
from ..deps import get_current_user
from ..security import make_traffic_token, verify_traffic_token
from ..models import (
    BoostStatus,
    GpuBoostRequest,
    Notification,
    NotebookRun,
    SsoToken,
    User,
    UserRole,
)
from ..schemas import BoostOut, BoostRequestCreate, NotificationOut
from ..timeutil import utcnow

router = APIRouter(prefix="/api/notebooks", tags=["notebooks"])
settings = get_settings()

VALID_PROFILES = {"small", "medium", "large", "gpu"}


def _sid(user: User) -> str:
    # Meaningless, stable hash of the IMMUTABLE account id (fixes N2/N3).
    return hashlib.sha256(user.id.encode()).hexdigest()[:16]


def _active_run(db, user: User) -> NotebookRun | None:
    return db.execute(
        select(NotebookRun).where(
            NotebookRun.user_id == user.id, NotebookRun.status == "active"
        )
    ).scalars().first()


@router.post("/launch")
async def launch(request: Request, user: User = Depends(get_current_user), db=Depends(get_db)):
    body = {}
    try:
        body = await request.json()
    except Exception:
        body = {}
    profile = (body or {}).get("profile", "medium")
    if profile not in VALID_PROFILES:
        profile = "medium"

    # Maintenance mode blocks new launches for everyone but admins/owner.
    if kv.is_maintenance(db) and user.role not in (UserRole.admin, UserRole.owner):
        msg = kv.get_setting(db, kv.MAINTENANCE_MSG, "") or \
            "The platform is in maintenance mode. Please try again shortly."
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, msg)

    # A granted, unconsumed boost upgrades this launch to multi-GPU.
    boost = db.execute(
        select(GpuBoostRequest).where(
            GpuBoostRequest.user_id == user.id,
            GpuBoostRequest.status == BoostStatus.approved,
        ).order_by(GpuBoostRequest.created_at.desc())
    ).scalars().first()

    # Per-user GPU-hours quota: drop to CPU (and skip any boost) once it's spent.
    if user.gpu_hours_limit is not None and (profile == "gpu" or boost is not None):
        used = scheduler.gpu_hours_used(db, user.id)
        if used >= user.gpu_hours_limit:
            profile = "medium" if profile == "gpu" else profile
            boost = None
            scheduler.notify(db, user.id, "warning",
                             f"GPU-hours quota reached ({used:.1f}/{user.gpu_hours_limit}h). "
                             "Running without GPU until an admin raises your quota.")
            db.commit()

    # Close out any previous run of this user before re-placing them.
    old = _active_run(db, user)
    if old:
        old.status = "stopped"
        old.stopped_at = utcnow()

    plan = scheduler.plan_placement(db, user.username, profile, boost=boost)
    sid = _sid(user)

    options: dict = {
        "profile": profile,
        "sid": sid,
        "mode": plan.mode,
        "share_gpu": plan.shared,
        "gpus": plan.gpus,
        # narrow read-only token so the in-Lab traffic widget can poll placement
        "traffic_token": make_traffic_token(user.username),
    }
    if plan.node:
        options["node"] = plan.node
    if plan.mode == "boost":
        options["ddp_nodes"] = plan.ddp_nodes
        options["rdzv"] = plan.rdzv

    try:
        await hub.ensure_user(user.username)
        await hub.start_server(user.username, options=options)
    except Exception:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "The notebook engine is temporarily unavailable. Please try again shortly.",
        )

    # Record the authoritative placement.
    db.add(NotebookRun(
        user_id=user.id, username=user.username, node_hostname=plan.node or "",
        profile=profile, mode=plan.mode, gpus=plan.gpus, shared=plan.shared,
        boost_id=boost.id if boost else None, status="active",
        extra={"ddp_nodes": plan.ddp_nodes, "rdzv": plan.rdzv} if plan.mode == "boost" else {},
    ))

    # Tell the people already on this node that they're now sharing it.
    for r in plan.colocated:
        if r.user_id != user.id:
            scheduler.notify(db, r.user_id, "warning",
                             f"{user.username} just started on your node ({plan.node}). "
                             "You're now sharing its GPU concurrently — both jobs keep running.")

    # Consume the one-session boost grant.
    if boost:
        boost.status = BoostStatus.consumed
        boost.consumed_at = utcnow()
        scheduler.notify(db, user.id, "boost",
                         f"GPU boost active: your job is spread across {plan.gpus} GPU node(s). "
                         "Use `satyameba-ddp your_script.py` to launch distributed training.")

    db.commit()

    token = secrets.token_urlsafe(32)
    db.add(SsoToken(
        token=token, username=user.username, profile=profile,
        expires_at=utcnow() + timedelta(seconds=settings.sso_token_ttl_seconds),
    ))
    db.commit()

    base = settings.hub_public_url.rstrip("/")
    nxt = quote(f"{base}/user/{user.username}/", safe="")
    url = f"{base}/sso-login?token={token}&next={nxt}"
    audit.record(db, action="notebook.launch", actor_id=user.id, actor_label=user.username,
                 detail={"profile": profile, "mode": plan.mode, "node": plan.node,
                         "gpus": plan.gpus, "boost": bool(boost)})
    return {"url": url, "profile": profile, "mode": plan.mode, "node": plan.node,
            "shared": plan.shared, "gpus": plan.gpus, "queued": plan.queued}


@router.post("/stop")
async def stop(user: User = Depends(get_current_user), db=Depends(get_db)):
    await hub.stop_server(user.username)
    run = _active_run(db, user)
    if run:
        run.status = "stopped"
        run.stopped_at = utcnow()
        freed = run.node_hostname
        db.commit()
        if freed:
            scheduler.on_run_stopped(db, freed)
            db.commit()
    audit.record(db, action="notebook.stop", actor_id=user.id, actor_label=user.username)
    return {"ok": True}


@router.get("/status")
async def nb_status(user: User = Depends(get_current_user)):
    active = await hub.list_active()
    mine = next((a for a in active if a["username"] == user.username), None)
    return mine or {"username": user.username, "active": False}


def _build_cluster(db, username: str) -> dict:
    """Live placement view: per-node occupancy + who `username` is sharing with."""
    nodes = scheduler.online_nodes(db)
    runs = scheduler.active_runs(db)
    by_host: dict[str, list[NotebookRun]] = {}
    for r in runs:
        by_host.setdefault(r.node_hostname, []).append(r)

    mine = next((r for r in runs if r.username == username), None)
    node_list = []
    for n in nodes:
        occ = by_host.get(n.hostname, [])
        node_list.append({
            "hostname": n.hostname,
            "role": n.role,
            "gpu": bool((n.labels or {}).get("gpu")),
            "draining": n.status.value == "draining",
            "occupants": len(occ),
            "you": bool(mine and mine.node_hostname == n.hostname),
        })

    sharing_with = 0
    busy = "idle"
    if mine and mine.node_hostname:
        peers = [r for r in by_host.get(mine.node_hostname, []) if r.username != username]
        sharing_with = len(peers)
        busy = "shared" if sharing_with else ("boost" if mine.mode == "boost" else "exclusive")

    return {
        "total_nodes": len(nodes),
        "active_users": len({r.user_id for r in runs}),
        "nodes": node_list,
        "you": {
            "active": bool(mine),
            "node": mine.node_hostname if mine else None,
            "mode": mine.mode if mine else None,
            "shared": bool(mine and mine.shared),
            "gpus": mine.gpus if mine else 0,
            "sharing_with": sharing_with,
            "status": busy,
        },
    }


@router.get("/cluster")
def cluster(user: User = Depends(get_current_user), db=Depends(get_db)):
    data = _build_cluster(db, user.username)
    data["maintenance"] = {"on": kv.is_maintenance(db),
                           "message": kv.get_setting(db, kv.MAINTENANCE_MSG, "")}
    return data


@router.get("/traffic")
def traffic(request: Request, db=Depends(get_db)):
    """Read-only placement feed for the in-Lab traffic widget. Authenticated by
    the narrow traffic token (header), not a user session."""
    tok = request.headers.get("x-sat-traffic-token", "")
    username = verify_traffic_token(tok)
    if not username:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid traffic token")
    return _build_cluster(db, username)


# Named PromQL for the per-user resource widget (RAM/VRAM/GPU/CPU).
_RES_Q = {
    "gpu_util": "avg(DCGM_FI_DEV_GPU_UTIL)",
    "vram_used": "sum(DCGM_FI_DEV_FB_USED)",          # MiB
    "vram_total": "sum(DCGM_FI_DEV_FB_USED) + sum(DCGM_FI_DEV_FB_FREE)",
    "ram_used_pct": "(1 - (sum(node_memory_MemAvailable_bytes) / sum(node_memory_MemTotal_bytes))) * 100",
    "cpu_pct": '100 - (avg(rate(node_cpu_seconds_total{mode="idle"}[2m])) * 100)',
}


@router.get("/resources")
async def resources(user: User = Depends(get_current_user)):
    """Best-effort live RAM/VRAM/GPU/CPU numbers from Prometheus for the widget.
    Returns nulls (not errors) when Prometheus/DCGM aren't wired yet."""
    async def _one(client, name, q):
        try:
            r = await client.get(f"{settings.prometheus_url}/api/v1/query", params={"query": q})
            res = r.json().get("data", {}).get("result", [])
            return name, (float(res[0]["value"][1]) if res else None)
        except Exception:
            return name, None
    try:
        async with httpx.AsyncClient(timeout=2) as client:
            import asyncio
            pairs = await asyncio.gather(*(_one(client, k, q) for k, q in _RES_Q.items()))
        return dict(pairs)
    except Exception:
        return {k: None for k in _RES_Q}


# --------------------------------------------------------------- GPU boost ----
@router.post("/boost/request", response_model=BoostOut, status_code=201)
def boost_request(payload: BoostRequestCreate, user: User = Depends(get_current_user),
                  db=Depends(get_db)):
    """Ask an admin for Kaggle-style multi-GPU power. Replaces any prior pending
    request from the same user so the queue stays clean."""
    for r in db.execute(select(GpuBoostRequest).where(
        GpuBoostRequest.user_id == user.id,
        GpuBoostRequest.status == BoostStatus.pending,
    )).scalars():
        r.status = BoostStatus.expired
    req = GpuBoostRequest(user_id=user.id, username=user.username,
                          gpus=payload.gpus, reason=payload.reason)
    db.add(req)
    db.commit()
    db.refresh(req)
    audit.record(db, action="boost.request", actor_id=user.id, actor_label=user.username,
                 detail={"gpus": payload.gpus})
    return req


@router.get("/boost/mine", response_model=BoostOut | None)
def boost_mine(user: User = Depends(get_current_user), db=Depends(get_db)):
    return db.execute(
        select(GpuBoostRequest).where(GpuBoostRequest.user_id == user.id)
        .order_by(GpuBoostRequest.created_at.desc())
    ).scalars().first()


# ------------------------------------------------------------ notifications ---
@router.get("/notifications", response_model=list[NotificationOut])
def notifications(user: User = Depends(get_current_user), db=Depends(get_db)):
    return list(db.execute(
        select(Notification).where(Notification.user_id == user.id)
        .order_by(Notification.read, Notification.created_at.desc()).limit(50)
    ).scalars())


@router.post("/notifications/read")
def mark_read(user: User = Depends(get_current_user), db=Depends(get_db)):
    for n in db.execute(select(Notification).where(
        Notification.user_id == user.id, Notification.read == False  # noqa: E712
    )).scalars():
        n.read = True
    db.commit()
    return {"ok": True}
