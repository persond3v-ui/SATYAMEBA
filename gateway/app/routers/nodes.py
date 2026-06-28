"""Worker node registration & heartbeat.

Workers authenticate to these endpoints using the internal shared secret (HMAC),
not a user token. The setup/join script on each worker calls /register once and
then /heartbeat on a timer, so the master always has a live view of the cluster.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit, scheduler
from ..config import get_settings
from ..database import get_db
from ..models import Node, NodeStatus
from ..schemas import NodeOut, NodeRegister
from ..security import verify_internal_token
from ..timeutil import aware, utcnow

router = APIRouter(prefix="/api/nodes", tags=["nodes"])
settings = get_settings()


def _check_internal(hostname: str, x_sat_node_token: str = Header(default="")) -> None:
    if not verify_internal_token(hostname, x_sat_node_token):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Bad node token")


@router.post("/register", response_model=NodeOut)
def register(
    payload: NodeRegister,
    x_sat_node_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    _check_internal(payload.hostname, x_sat_node_token)
    node = db.execute(
        select(Node).where(Node.hostname == payload.hostname)
    ).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if node is None:
        node = Node(
            hostname=payload.hostname,
            ip=payload.ip,
            role=payload.role,
            swarm_node_id=payload.swarm_node_id,
            labels=payload.labels,
            status=NodeStatus.online,
            last_heartbeat=now,
        )
        db.add(node)
    else:
        node.ip = payload.ip or node.ip
        node.role = payload.role or node.role
        node.swarm_node_id = payload.swarm_node_id or node.swarm_node_id
        node.labels = payload.labels or node.labels
        node.status = NodeStatus.online
        node.last_heartbeat = now
    db.commit()
    db.refresh(node)
    audit.record(db, action="node.register", actor_label=payload.hostname,
                 target=payload.hostname, detail={"ip": payload.ip, "role": payload.role})
    return node


@router.post("/heartbeat")
def heartbeat(
    payload: NodeRegister,
    x_sat_node_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    _check_internal(payload.hostname, x_sat_node_token)
    node = db.execute(
        select(Node).where(Node.hostname == payload.hostname)
    ).scalar_one_or_none()
    if node is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Register first")
    node.last_heartbeat = datetime.now(timezone.utc)
    # Don't undo an admin-set drain: a draining node stays out of the scheduler
    # until an admin explicitly re-activates it.
    if node.status != NodeStatus.draining:
        node.status = NodeStatus.online
    if payload.labels:
        node.labels = payload.labels
    db.commit()
    return {"ok": True}


@router.get("/dashboard")
def dashboard(
    x_sat_node_name: str = Header(default=""),
    x_sat_node_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    """Read-only cluster health for the on-console curses TUI (a node calls this
    with its own token). Returns per-node health + the users active on each."""
    _check_internal(x_sat_node_name, x_sat_node_token)
    cutoff = settings.node_offline_seconds
    runs = scheduler.active_runs(db)
    by_host: dict[str, list[str]] = {}
    for r in runs:
        by_host.setdefault(r.node_hostname, []).append(r.username)
    out = []
    for n in db.execute(select(Node).order_by(Node.role.desc(), Node.hostname)).scalars():
        hb = aware(n.last_heartbeat)
        age = (utcnow() - hb).total_seconds() if hb else None
        if n.status == NodeStatus.draining:
            state = "draining"
        elif age is None or age > cutoff:
            state = "offline"
        else:
            state = "online"
        out.append({
            "hostname": n.hostname, "role": n.role, "state": state,
            "gpu": bool((n.labels or {}).get("gpu")),
            "heartbeat_age": int(age) if age is not None else None,
            "users": sorted(by_host.get(n.hostname, [])),
        })
    return {
        "nodes": out,
        "active_users": len({r.username for r in runs}),
        "total_nodes": len(out),
        "online_nodes": sum(1 for n in out if n["state"] == "online"),
    }
