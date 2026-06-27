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

from .. import audit
from ..config import get_settings
from ..database import get_db
from ..models import Node, NodeStatus
from ..schemas import NodeOut, NodeRegister
from ..security import verify_internal_token

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
    node.status = NodeStatus.online
    if payload.labels:
        node.labels = payload.labels
    db.commit()
    return {"ok": True}
