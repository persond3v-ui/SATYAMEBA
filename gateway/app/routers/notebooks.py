"""User-facing notebook lifecycle.

The gateway brokers all Hub calls (the SPA never holds Hub admin credentials).
Launch flow with single sign-on (no second login):

  1. SPA POSTs /launch with a desired resource ``profile``.
  2. Gateway tells the Hub to start the user's server with that profile, then
     mints a single-use SSO token and returns an ``/hub/sso-login`` URL.
  3. The SPA opens that URL in a new tab; the Hub's SSO login handler redeems the
     token against the gateway, logs the browser in, and lands on JupyterLab.

Docker Swarm places the spawned server on an available node (load balancing);
the reserved CPU/RAM/GPU come from the chosen profile (payload-aware).
"""
from __future__ import annotations

import secrets
from datetime import timedelta
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, status

from .. import audit, hub
from ..config import get_settings
from ..database import get_db
from ..deps import get_current_user
from ..models import SsoToken, User
from ..timeutil import utcnow

router = APIRouter(prefix="/api/notebooks", tags=["notebooks"])
settings = get_settings()

VALID_PROFILES = {"small", "medium", "large", "gpu"}


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

    try:
        await hub.ensure_user(user.username)
        await hub.start_server(user.username, options={"profile": profile})
    except Exception:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "The notebook engine is temporarily unavailable. Please try again shortly.",
        )

    token = secrets.token_urlsafe(32)
    db.add(SsoToken(
        token=token,
        username=user.username,
        profile=profile,
        expires_at=utcnow() + timedelta(seconds=settings.sso_token_ttl_seconds),
    ))
    db.commit()

    base = settings.hub_public_url.rstrip("/")
    nxt = quote(f"{base}/user/{user.username}/", safe="")
    url = f"{base}/sso-login?token={token}&next={nxt}"
    audit.record(db, action="notebook.launch", actor_id=user.id,
                 actor_label=user.username, detail={"profile": profile})
    return {"url": url, "profile": profile}


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
