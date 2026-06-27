"""In-process sliding-window rate limiter (OWASP A04/A07 — brute force / DoS).

For a single gateway replica this is sufficient. When you scale the gateway to
multiple replicas, point ``SAT_RATE_LIMIT_BACKEND`` at Redis instead — the
interface here is deliberately small so that swap is a drop-in. The setup script
notes this in the generated README section.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from ..config import get_settings

settings = get_settings()


class _Window:
    def __init__(self) -> None:
        self.hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str, limit: int, window: float = 60.0) -> bool:
        now = time.monotonic()
        q = self.hits[key]
        while q and q[0] <= now - window:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        return True


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app) -> None:
        super().__init__(app)
        self._win = _Window()

    def _client_ip(self, request: Request) -> str:
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    async def dispatch(self, request: Request, call_next) -> Response:
        ip = self._client_ip(request)
        path = request.url.path
        # Tighter budget on auth endpoints to slow credential stuffing.
        is_auth = path.startswith("/api/auth")
        limit = settings.auth_rate_limit_per_minute if is_auth else settings.rate_limit_per_minute
        key = f"{ip}:{'auth' if is_auth else 'general'}"
        if not self._win.allow(key, limit):
            return JSONResponse(
                {"detail": "Too many requests. Slow down."},
                status_code=429,
                headers={"Retry-After": "30"},
            )
        return await call_next(request)
