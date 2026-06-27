"""SATYAMEBA JupyterHub authenticator + single sign-on.

Identity lives in the gateway database, not the Hub. This authenticator supports
two paths, both validated against the gateway (guarded by the internal shared
secret) and both gated on the user being *approved*:

  * username/password  -> POST /api/internal/authenticate  (manual Hub login)
  * one-time SSO token -> POST /api/internal/redeem-ott     (handoff from the SPA)

The ``SSOLoginHandler`` lets the SPA open ``/hub/sso-login?token=...&next=...``
so a user who is already logged into SATYAMEBA lands straight in JupyterLab with
no second login.
"""
from __future__ import annotations

import json
import os
from urllib.parse import urlparse

from jupyterhub.auth import Authenticator
from jupyterhub.handlers import BaseHandler
from jupyterhub.utils import url_path_join
from tornado import web
from tornado.httpclient import AsyncHTTPClient, HTTPRequest
from traitlets import Unicode


class SatyamebaAuthenticator(Authenticator):
    gateway_url = Unicode(
        os.environ.get("SAT_HUB_GATEWAY_URL", "http://gateway:8000"), config=True,
        help="Base URL of the SATYAMEBA gateway.",
    )
    internal_secret = Unicode(
        os.environ.get("SAT_INTERNAL_SHARED_SECRET", ""), config=True,
        help="Shared secret presented to the gateway internal API.",
    )

    async def _call(self, path: str, payload: dict):
        client = AsyncHTTPClient()
        req = HTTPRequest(
            url=f"{self.gateway_url}{path}",
            method="POST",
            headers={"Content-Type": "application/json", "X-SAT-Internal": self.internal_secret},
            body=json.dumps(payload),
            request_timeout=10,
        )
        try:
            resp = await client.fetch(req, raise_error=False)
        except Exception as exc:
            self.log.warning("gateway call failed: %s", exc)
            return None
        if resp.code != 200:
            return None
        data = json.loads(resp.body.decode())
        return {"name": data["name"], "admin": bool(data.get("admin", False))}

    async def authenticate(self, handler, data):
        # SSO one-time token path.
        if data and data.get("ott"):
            return await self._call("/api/internal/redeem-ott", {"token": data["ott"]})
        # Username/password path.
        username = (data or {}).get("username", "").strip().lower()
        password = (data or {}).get("password", "")
        if not username or not password:
            return None
        return await self._call("/api/internal/authenticate",
                                {"username": username, "password": password})

    def get_handlers(self, app):
        return super().get_handlers(app) + [(r"/sso-login", SSOLoginHandler)]


class SSOLoginHandler(BaseHandler):
    """Redeems an SPA-issued one-time token and logs the browser into the Hub."""

    async def get(self):
        token = self.get_argument("token", "")
        nxt = self.get_argument("next", "")
        if not token:
            raise web.HTTPError(400, "missing token")
        user = await self.login_user({"ott": token})
        if user is None:
            raise web.HTTPError(403, "invalid or expired SSO token")
        # Only allow same-site, path-relative redirects (no open redirect).
        parsed = urlparse(nxt)
        if not nxt or parsed.scheme or parsed.netloc or nxt.startswith("//"):
            nxt = url_path_join(self.hub.base_url, "user", user.name) + "/"
        self.redirect(nxt)
