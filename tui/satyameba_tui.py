#!/usr/bin/env python3
"""SATYAMEBA console dashboard (curses).

A neon, any-resolution terminal dashboard for the lab monitors when the desktop
environment has been removed to save RAM. Shows, live:

  * each node's health (online / draining / offline + heartbeat age)
  * the users active on each node
  * cluster totals

It reads connection details from /etc/satyameba/node.env (written by the setup
wizard / worker-join):

    SAT_GATEWAY_URL=https://192.168.1.10
    SAT_NODE_HOSTNAME=worker-1
    SAT_NODE_TOKEN=<hmac node token>
    SAT_CA_BUNDLE=/path/to/ca.pem      # optional; omit on self-signed labs

Runs on tty1 as a systemd service, or on demand over SSH:  satyameba-tui
Press q to quit, r to refresh now. Resilient: a tiny terminal or an unreachable
gateway shows a friendly screen instead of crashing.
"""
from __future__ import annotations

import curses
import json
import os
import ssl
import time
import urllib.request

REFRESH_SECONDS = 5
ENV_FILE = os.environ.get("SAT_NODE_ENV", "/etc/satyameba/node.env")


def _load_env() -> dict:
    cfg = dict(os.environ)
    try:
        with open(ENV_FILE) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    cfg.setdefault(k.strip(), v.strip().strip('"'))
    except OSError:
        pass
    return cfg


def fetch(cfg: dict) -> tuple[dict | None, str]:
    base = cfg.get("SAT_GATEWAY_URL", "").rstrip("/")
    if not base:
        return None, "SAT_GATEWAY_URL not set in /etc/satyameba/node.env"
    url = f"{base}/api/nodes/dashboard"
    req = urllib.request.Request(url, headers={
        "X-SAT-Node-Name": cfg.get("SAT_NODE_HOSTNAME", ""),
        "X-SAT-Node-Token": cfg.get("SAT_NODE_TOKEN", ""),
    })
    ca = cfg.get("SAT_CA_BUNDLE")
    if ca and os.path.exists(ca):
        ctx = ssl.create_default_context(cafile=ca)
    else:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE  # self-signed lab default
    try:
        with urllib.request.urlopen(req, timeout=4, context=ctx) as r:
            return json.loads(r.read().decode()), ""
    except Exception as e:  # noqa: BLE001
        return None, f"cannot reach gateway: {e}"


def _safe_add(win, y, x, text, attr=0):
    h, w = win.getmaxyx()
    if y < 0 or y >= h or x >= w:
        return
    try:
        win.addnstr(y, x, text, max(0, w - x - 1), attr)
    except curses.error:
        pass


def _colors():
    curses.start_color()
    try:
        curses.use_default_colors()
        bg = -1
    except curses.error:
        bg = curses.COLOR_BLACK
    curses.init_pair(1, curses.COLOR_CYAN, bg)
    curses.init_pair(2, curses.COLOR_GREEN, bg)
    curses.init_pair(3, curses.COLOR_YELLOW, bg)
    curses.init_pair(4, curses.COLOR_RED, bg)
    curses.init_pair(5, curses.COLOR_MAGENTA, bg)


STATE_COLOR = {"online": 2, "draining": 3, "offline": 4}


def draw(stdscr, cfg, data, err):
    stdscr.erase()
    h, w = stdscr.getmaxyx()
    title = "◆ SATYAMEBA — cluster console"
    _safe_add(stdscr, 0, 1, title, curses.color_pair(5) | curses.A_BOLD)
    _safe_add(stdscr, 0, max(1, w - 22), time.strftime("%Y-%m-%d %H:%M:%S"),
              curses.color_pair(1))
    _safe_add(stdscr, 1, 1, "─" * (w - 2), curses.color_pair(5))

    if not data:
        _safe_add(stdscr, 3, 2, "Waiting for the gateway…", curses.color_pair(3) | curses.A_BOLD)
        _safe_add(stdscr, 4, 2, err or "", curses.color_pair(4))
        _safe_add(stdscr, h - 1, 1, " q quit · r refresh ", curses.color_pair(1))
        stdscr.refresh()
        return

    summary = (f"nodes {data.get('online_nodes', 0)}/{data.get('total_nodes', 0)} online"
               f"   ·   active users: {data.get('active_users', 0)}")
    _safe_add(stdscr, 2, 2, summary, curses.color_pair(1) | curses.A_BOLD)

    row = 4
    for n in data.get("nodes", []):
        if row >= h - 1:
            break
        state = n.get("state", "offline")
        cp = curses.color_pair(STATE_COLOR.get(state, 4))
        dot = "●"
        gpu = " GPU" if n.get("gpu") else "    "
        age = n.get("heartbeat_age")
        age_s = f"{age}s ago" if age is not None else "—"
        head = f"{dot} {n.get('hostname',''):<18} {n.get('role',''):<7}{gpu}  {state:<9} hb:{age_s}"
        _safe_add(stdscr, row, 2, head, cp | curses.A_BOLD)
        row += 1
        users = n.get("users", [])
        line = ("   users: " + (", ".join(users) if users else "—"))
        _safe_add(stdscr, row, 2, line, curses.color_pair(1))
        row += 2

    _safe_add(stdscr, h - 1, 1,
              " q quit · r refresh · auto every %ss " % REFRESH_SECONDS,
              curses.color_pair(5))
    stdscr.refresh()


def main(stdscr):
    curses.curs_set(0)
    _colors()
    stdscr.nodelay(True)
    cfg = _load_env()
    data, err = fetch(cfg)
    last = time.time()
    draw(stdscr, cfg, data, err)
    while True:
        try:
            ch = stdscr.getch()
        except curses.error:
            ch = -1
        if ch in (ord("q"), ord("Q")):
            break
        if ch in (ord("r"), ord("R")) or (time.time() - last) >= REFRESH_SECONDS:
            cfg = _load_env()
            data, err = fetch(cfg)
            last = time.time()
            draw(stdscr, cfg, data, err)
        if ch == curses.KEY_RESIZE:
            draw(stdscr, cfg, data, err)
        time.sleep(0.1)


if __name__ == "__main__":
    try:
        curses.wrapper(main)
    except KeyboardInterrupt:
        pass
