"""Network helpers."""
from __future__ import annotations

from starlette.requests import Request


def client_ip(request: Request) -> str:
    """Return the real client IP as seen by the trusted edge.

    nginx sets ``X-Forwarded-For: <client-supplied>, <edge-observed-ip>`` via
    ``$proxy_add_x_forwarded_for``. The client-supplied part is spoofable, so we
    take the **rightmost** entry (the one our own edge appended). With exactly one
    trusted proxy this is the genuine source IP — using the leftmost would let an
    attacker forge IPs to dodge rate limits and poison the audit log.
    """
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        parts = [p.strip() for p in fwd.split(",") if p.strip()]
        if parts:
            return parts[-1]
    return request.client.host if request.client else "unknown"
