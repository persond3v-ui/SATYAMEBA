"""Prometheus request metrics. Labels use a coarse path group (first two path
segments, e.g. ``/api/admin``) to keep cardinality bounded — user ids and tokens
in the path never become label values."""
from __future__ import annotations

import time

from prometheus_client import Counter, Histogram
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

REQUESTS = Counter(
    "satyameba_http_requests_total", "HTTP requests", ["method", "group", "code"]
)
LATENCY = Histogram(
    "satyameba_http_request_seconds", "HTTP request latency", ["method", "group"]
)


def _group(path: str) -> str:
    parts = [p for p in path.split("/") if p]
    return "/" + "/".join(parts[:2]) if parts else "/"


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        group = _group(request.url.path)
        REQUESTS.labels(request.method, group, str(response.status_code)).inc()
        LATENCY.labels(request.method, group).observe(time.perf_counter() - start)
        return response
