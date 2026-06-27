"""Verify per-session HMAC request signatures on state-changing requests.

The SPA attaches three headers to every protected request:
    X-SAT-Timestamp : unix seconds
    X-SAT-Nonce     : random per-request token
    X-SAT-Signature : hex HMAC-SHA256 over canonical(method,path,ts,nonce,body)

We reject anything outside the allowed clock skew (replay window) and any nonce
we have already seen inside that window (hard replay block). The signing key is
looked up from the authenticated session, so this layers on top of the bearer
token rather than replacing it.

Implemented as a *pure ASGI* middleware (not BaseHTTPMiddleware) because we must
read the request body to verify the signature and then replay it to the inner
app — BaseHTTPMiddleware would consume the receive stream and starve the route.
"""
from __future__ import annotations

import json
import time

from sqlalchemy import select

from ..config import get_settings
from ..database import SessionLocal
from ..models import UserSession
from ..ratestore import store
from ..security import decode_token, verify_signature

settings = get_settings()

_EXEMPT_PREFIXES = (
    "/api/auth/register",
    "/api/auth/login",
    "/api/auth/refresh",
    "/api/internal",
    "/api/nodes/register",
    "/api/nodes/heartbeat",
    "/healthz",
    "/metrics",
    "/docs",
    "/openapi.json",
)


class RequestSigningMiddleware:
    def __init__(self, app) -> None:
        self.app = app

    async def _reject(self, send, status: int, detail: str) -> None:
        body = json.dumps({"detail": detail}).encode()
        await send({
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode())],
        })
        await send({"type": "http.response.body", "body": body})

    def _exempt(self, method: str, path: str) -> bool:
        if not settings.request_signing_enabled:
            return True
        if method.upper() not in settings.request_signing_protect_methods:
            return True
        return any(path.startswith(p) for p in _EXEMPT_PREFIXES)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "GET")
        path = scope.get("path", "")
        if self._exempt(method, path):
            await self.app(scope, receive, send)
            return

        # Drain the body so we can both verify and replay it downstream.
        chunks = []
        more = True
        while more:
            msg = await receive()
            if msg["type"] == "http.request":
                chunks.append(msg.get("body", b""))
                more = msg.get("more_body", False)
            elif msg["type"] == "http.disconnect":
                more = False
        body = b"".join(chunks)

        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        ts = headers.get("x-sat-timestamp", "")
        nonce = headers.get("x-sat-nonce", "")
        sig = headers.get("x-sat-signature", "")
        if not (ts and nonce and sig):
            return await self._reject(send, 400, "Request signature required")
        try:
            skew = abs(time.time() - float(ts))
        except ValueError:
            return await self._reject(send, 400, "Bad timestamp")
        if skew > settings.request_signing_skew_seconds:
            return await self._reject(send, 401, "Signature timestamp outside window")
        if store.seen_nonce(nonce, settings.request_signing_skew_seconds * 2):
            return await self._reject(send, 401, "Replay detected")

        auth = headers.get("authorization", "")
        if not auth.lower().startswith("bearer "):
            return await self._reject(send, 401, "Missing bearer token")
        try:
            payload = decode_token(auth.split(" ", 1)[1].strip())
        except Exception:
            return await self._reject(send, 401, "Invalid token")

        db = SessionLocal()
        try:
            sess = db.execute(
                select(UserSession).where(UserSession.jti == payload.get("jti", ""))
            ).scalar_one_or_none()
        finally:
            db.close()
        if sess is None or sess.revoked:
            return await self._reject(send, 401, "Session revoked")

        if not verify_signature(sess.signing_key, sig, method, path, ts, nonce, body):
            return await self._reject(send, 401, "Bad request signature")

        # Replay the buffered body to the downstream app.
        replayed = False

        async def replay_receive():
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, replay_receive, send)
