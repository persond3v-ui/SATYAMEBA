"""Best-effort bot / automated-client filtering.

Honest scope: this raises the cost of casual scraping and naive automation. It
is NOT a hard wall — a determined adversary can forge headers. The durable
defenses in SATYAMEBA are admin approval gating, rate limiting, and request
signing. This middleware simply trims obvious noise.
"""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from ..config import get_settings

settings = get_settings()

_BLOCK_UA_SUBSTRINGS = (
    "sqlmap", "nikto", "nmap", "masscan", "dirbuster", "gobuster", "wpscan",
    "havij", "acunetix", "nessus", "zgrab", "python-requests/0",  # default scripts
)
# Endpoints a normal browser hits without a referer are fine; APIs we gate.
_PROTECTED_PREFIXES = ("/api/admin", "/api/notebooks")


class BotFilterMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        if not settings.bot_filter_enabled:
            return await call_next(request)

        ua = request.headers.get("user-agent", "").lower()
        if not ua:
            return JSONResponse({"detail": "Forbidden"}, status_code=403)
        if any(bad in ua for bad in _BLOCK_UA_SUBSTRINGS):
            return JSONResponse({"detail": "Forbidden"}, status_code=403)

        # Obvious header-shape checks for sensitive APIs.
        path = request.url.path
        if any(path.startswith(p) for p in _PROTECTED_PREFIXES):
            accept = request.headers.get("accept", "")
            if "application/json" not in accept and "*/*" not in accept:
                return JSONResponse({"detail": "Forbidden"}, status_code=403)

        return await call_next(request)
