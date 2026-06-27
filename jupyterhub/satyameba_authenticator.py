"""SATYAMEBA JupyterHub authenticator.

Identity lives in the gateway database, not in the Hub. This authenticator
forwards the submitted username/password to the gateway's internal
``/api/internal/authenticate`` endpoint (guarded by the internal shared secret)
and only lets *approved* users in. Suspended/pending/rejected users are bounced
even if they once had a Hub account.
"""
from __future__ import annotations

import os

from jupyterhub.auth import Authenticator
from tornado.httpclient import AsyncHTTPClient, HTTPRequest
from traitlets import Unicode
import json


class SatyamebaAuthenticator(Authenticator):
    gateway_url = Unicode(
        os.environ.get("SAT_HUB_GATEWAY_URL", "http://gateway:8000"),
        config=True,
        help="Base URL of the SATYAMEBA gateway.",
    )
    internal_secret = Unicode(
        os.environ.get("SAT_INTERNAL_SHARED_SECRET", ""),
        config=True,
        help="Shared secret presented to the gateway internal API.",
    )

    async def authenticate(self, handler, data):
        username = (data or {}).get("username", "").strip().lower()
        password = (data or {}).get("password", "")
        if not username or not password:
            return None
        client = AsyncHTTPClient()
        req = HTTPRequest(
            url=f"{self.gateway_url}/api/internal/authenticate",
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-SAT-Internal": self.internal_secret,
            },
            body=json.dumps({"username": username, "password": password}),
            request_timeout=10,
        )
        try:
            resp = await client.fetch(req, raise_error=False)
        except Exception as exc:  # network hiccup -> deny, fail closed
            self.log.warning("gateway auth call failed: %s", exc)
            return None
        if resp.code != 200:
            return None
        payload = json.loads(resp.body.decode())
        return {
            "name": payload["name"],
            "admin": bool(payload.get("admin", False)),
        }
