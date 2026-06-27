"""Tornado handlers + a defensive HTML transform that injects the traffic strip.

The strip is loaded by rewriting the JupyterLab HTML page to add one
``<script>`` tag. The transform swallows *every* error and only ever touches
``text/html`` bodies, so it can never break the notebook — if anything is off,
you simply don't see the strip (the neon theme + nvdashboard + resource-usage
still work). That graceful degradation is deliberate: failsafe over clever.
"""
from __future__ import annotations

import json
import os

from jupyter_server.base.handlers import JupyterHandler
from jupyter_server.utils import url_path_join
from tornado import web

try:
    import httpx
except Exception:  # pragma: no cover
    httpx = None

_STATIC = os.path.join(os.path.dirname(__file__), "static")


class TrafficProxyHandler(JupyterHandler):
    """Same-origin proxy: add the server-side traffic token, forward to gateway."""

    @web.authenticated
    async def get(self):
        gateway = os.environ.get("SATYAMEBA_GATEWAY_URL", "http://gateway:8000")
        token = os.environ.get("SATYAMEBA_TRAFFIC_TOKEN", "")
        self.set_header("Content-Type", "application/json")
        if not token:
            self.finish(json.dumps({"unavailable": True}))
            return
        url = f"{gateway.rstrip('/')}/api/notebooks/traffic"
        try:
            if httpx is not None:
                async with httpx.AsyncClient(timeout=3) as c:
                    r = await c.get(url, headers={"X-SAT-Traffic-Token": token})
                    body, code = r.text, r.status_code
            else:  # pragma: no cover
                import urllib.request
                req = urllib.request.Request(url, headers={"X-SAT-Traffic-Token": token})
                with urllib.request.urlopen(req, timeout=3) as resp:
                    body, code = resp.read().decode(), resp.status
        except Exception:
            body, code = json.dumps({"unavailable": True}), 200
        self.set_status(code)
        self.finish(body)


def _make_transform(base_url: str):
    from tornado.web import OutputTransform

    src = url_path_join(base_url, "satyameba", "static", "strip.js")
    snippet = f'<script defer src="{src}"></script></body>'.encode()

    class StripInjector(OutputTransform):
        def __init__(self, request):
            self._html = False

        def transform_first_chunk(self, status_code, headers, chunk, finishing):
            try:
                ctype = headers.get("Content-Type", "")
                if "text/html" in ctype and b"</body>" in chunk:
                    self._html = True
                    chunk = chunk.replace(b"</body>", snippet, 1)
                    if "Content-Length" in headers:
                        headers["Content-Length"] = str(len(chunk))
            except Exception:
                pass
            return status_code, headers, chunk

        def transform_chunk(self, chunk, finishing):
            return chunk

    return StripInjector


def setup_handlers(web_app):
    host = web_app.settings["host_pattern"]
    base = web_app.settings["base_url"]
    api = url_path_join(base, "satyameba", "api", "traffic")
    static = url_path_join(base, "satyameba", "static", "(.*)")
    web_app.add_handlers(host, [
        (api, TrafficProxyHandler),
        (static, web.StaticFileHandler, {"path": _STATIC}),
    ])
    try:
        web_app.add_transform(_make_transform(base))
    except Exception:
        pass  # injection is best-effort; never break the page
