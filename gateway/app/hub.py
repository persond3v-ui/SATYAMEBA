"""Thin JupyterHub REST client used by the gateway to drive notebook servers.

The gateway is the only component that talks to the Hub admin API; users never
get the Hub admin token. We create/remove Hub users to mirror approval state and
start/stop single-user servers on demand.
"""
from __future__ import annotations

import httpx

from .config import get_settings

settings = get_settings()


def _headers() -> dict:
    return {"Authorization": f"token {settings.hub_api_token}"}


async def ensure_user(username: str, admin: bool = False) -> None:
    async with httpx.AsyncClient(base_url=settings.hub_api_url, timeout=10) as c:
        r = await c.get(f"/users/{username}", headers=_headers())
        if r.status_code == 404:
            await c.post(
                f"/users/{username}",
                headers=_headers(),
                json={"admin": admin},
            )
        elif r.status_code == 200 and admin:
            await c.patch(f"/users/{username}", headers=_headers(), json={"admin": True})


async def delete_user(username: str) -> None:
    async with httpx.AsyncClient(base_url=settings.hub_api_url, timeout=10) as c:
        # stop server first, then remove
        await c.delete(f"/users/{username}/server", headers=_headers())
        await c.delete(f"/users/{username}", headers=_headers())


async def start_server(username: str) -> str:
    async with httpx.AsyncClient(base_url=settings.hub_api_url, timeout=30) as c:
        await c.post(f"/users/{username}/server", headers=_headers())
    return f"{settings.hub_public_url}/user/{username}/"


async def stop_server(username: str) -> None:
    async with httpx.AsyncClient(base_url=settings.hub_api_url, timeout=30) as c:
        await c.delete(f"/users/{username}/server", headers=_headers())


async def list_active() -> list[dict]:
    async with httpx.AsyncClient(base_url=settings.hub_api_url, timeout=10) as c:
        r = await c.get("/users", headers=_headers())
        if r.status_code != 200:
            return []
        out = []
        for u in r.json():
            servers = u.get("servers") or {}
            out.append(
                {
                    "username": u.get("name"),
                    "active": bool(servers),
                    "last_activity": u.get("last_activity"),
                }
            )
        return out
