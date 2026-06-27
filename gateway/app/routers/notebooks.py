"""User-facing notebook lifecycle. The gateway brokers all Hub calls so the SPA
never holds Hub admin credentials. Spawned servers are placed on the cluster by
Docker Swarm's scheduler (load balancing across available nodes)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from .. import audit, hub
from ..database import get_db
from ..deps import get_current_user
from ..models import User
from ..security import internal_token

router = APIRouter(prefix="/api/notebooks", tags=["notebooks"])


@router.post("/launch")
async def launch(request: Request, user: User = Depends(get_current_user), db=Depends(get_db)):
    await hub.ensure_user(user.username)
    url = await hub.start_server(user.username)
    audit.record(db, action="notebook.launch", actor_id=user.id, actor_label=user.username)
    # The SPA redirects the browser to the Hub, carrying a one-time internal
    # handshake token the Hub authenticator validates against the gateway.
    return {"url": url, "handshake": internal_token(user.username)}


@router.post("/stop")
async def stop(user: User = Depends(get_current_user), db=Depends(get_db)):
    await hub.stop_server(user.username)
    audit.record(db, action="notebook.stop", actor_id=user.id, actor_label=user.username)
    return {"ok": True}


@router.get("/status")
async def status(user: User = Depends(get_current_user)):
    active = await hub.list_active()
    mine = next((a for a in active if a["username"] == user.username), None)
    return mine or {"username": user.username, "active": False}
