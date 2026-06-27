"""SATYAMEBA in-notebook traffic server extension.

A *pure-Python* Jupyter Server extension (no front-end build required) that:

  * serves ``/satyameba/static/strip.js`` — a tiny vanilla-JS widget that shows
    your node, whether you're sharing it (and with how many people), live
    GPU/VRAM/RAM/CPU, and a "Request more GPUs" button;
  * exposes ``/satyameba/api/traffic`` — a same-origin proxy that adds the
    narrow ``SATYAMEBA_TRAFFIC_TOKEN`` (kept server-side, never sent to the
    browser) and forwards to the gateway, so the widget gets live placement
    without holding any credential.

The widget is loaded by the optional ``satyameba-traffic`` labextension; if that
isn't built, the neon theme + jupyter-resource-usage + nvdashboard still give a
fully-featured notebook (graceful degradation — failsafe).
"""
from __future__ import annotations

import os

from ._handlers import setup_handlers


def _jupyter_server_extension_points():
    return [{"module": "satyameba_traffic"}]


def _load_jupyter_server_extension(server_app):
    setup_handlers(server_app.web_app)
    server_app.log.info("[satyameba_traffic] loaded (node=%s mode=%s)",
                        os.environ.get("SATYAMEBA_NODE", "?"),
                        os.environ.get("SATYAMEBA_MODE", "?"))


# Back-compat alias for older jupyter_server.
load_jupyter_server_extension = _load_jupyter_server_extension
