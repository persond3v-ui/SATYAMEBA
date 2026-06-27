"""Rate limiter (OWASP A04/A07 — brute force / DoS).

Backed by the shared store (Redis when configured), so limits hold across
gateway replicas.
"""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from ..config import get_settings
from ..ratestore import store

settings = get_settings()


class RateLimitMiddleware(BaseHTTPMiddleware):
    def _client_ip(self, request: Request) -> str:
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    async def dispatch(self, request: Request, call_next) -> Response:
        ip = self._client_ip(request)
        path = request.url.path
        is_auth = path.startswith("/api/auth")
        limit = settings.auth_rate_limit_per_minute if is_auth else settings.rate_limit_per_minute
        key = f"{ip}:{'auth' if is_auth else 'general'}"
        if not store.allow(key, limit, window=60.0):
            return JSONResponse(
                {"detail": "Too many requests. Slow down."},
                status_code=429,
                headers={"Retry-After": "30"},
            )
        return await call_next(request)
