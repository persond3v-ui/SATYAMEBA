#!/usr/bin/env python3
"""Generate the SATYAMEBA DFDs (Level 0/1/2) + lifecycle flowchart as SVG, and
render matching PNGs. Run:  python docs/diagrams/generate.py

Diagrams are annotated with the flaw findings (red callouts, ⚠ Nn) from the
second integration scan so the architecture and its risks are visible together.
"""
from __future__ import annotations

import os

import cairosvg

HERE = os.path.dirname(__file__)

# palette
BG = "#0e1116"; PANEL = "#161b22"; PANEL2 = "#1c232d"; BORDER = "#2a323d"
TEXT = "#e6edf3"; MUTED = "#8b949e"; ACCENT = "#f5a623"; BLUE = "#4c8dff"
OK = "#3fb950"; BAD = "#f85149"; WARN = "#d29922"; PURPLE = "#a371f7"

FONT = "DejaVu Sans, Arial, sans-serif"
MONO = "DejaVu Sans Mono, monospace"


def esc(s): return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class C:
    """Canvas: collects svg fragments."""
    def __init__(self, w, h, title):
        self.w, self.h, self.title = w, h, title
        self.body = []

    def add(self, s): self.body.append(s)

    def text(self, x, y, s, size=14, color=TEXT, anchor="middle", mono=False, weight="normal"):
        f = MONO if mono else FONT
        self.add(f'<text x="{x}" y="{y}" fill="{color}" font-family="{f}" '
                 f'font-size="{size}" text-anchor="{anchor}" font-weight="{weight}">{esc(s)}</text>')

    def lines(self, cx, y, items, size=13, color=TEXT, gap=16, anchor="middle", mono=False, weight="normal"):
        for i, ln in enumerate(items):
            self.text(cx, y + i * gap, ln, size, color, anchor, mono, weight)

    def box(self, x, y, w, h, title, sub=None, stroke=BLUE, fill=PANEL, rx=10, tsize=15):
        self.add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" '
                 f'fill="{fill}" stroke="{stroke}" stroke-width="2"/>')
        cx = x + w / 2
        if sub:
            self.text(cx, y + h / 2 - 4, title, tsize, TEXT, weight="bold")
            if isinstance(sub, list):
                self.lines(cx, y + h / 2 + 14, sub, 11.5, MUTED, 13)
            else:
                self.text(cx, y + h / 2 + 14, sub, 11.5, MUTED)
        else:
            self.text(cx, y + h / 2 + 5, title, tsize, TEXT, weight="bold")
        return Anchor(x, y, w, h)

    def entity(self, x, y, w, h, title, sub=None):
        return self.box(x, y, w, h, title, sub, stroke=ACCENT, fill=PANEL2, rx=3)

    def store(self, x, y, w, h, tag, title):
        # open-ended data store (top/bottom rules + id tab)
        self.add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="2" fill="#12161c" stroke="{BORDER}"/>')
        self.add(f'<line x1="{x}" y1="{y}" x2="{x+w}" y2="{y}" stroke="{PURPLE}" stroke-width="2.5"/>')
        self.add(f'<line x1="{x}" y1="{y+h}" x2="{x+w}" y2="{y+h}" stroke="{PURPLE}" stroke-width="2.5"/>')
        self.text(x + 26, y + h / 2 + 4, tag, 12, PURPLE, "middle", mono=True, weight="bold")
        self.text(x + 38 + (w - 38) / 2, y + h / 2 + 4, title, 12.5, TEXT)
        return Anchor(x, y, w, h)

    def flow(self, p1, p2, label=None, both=False, color=ACCENT, dash=False, lx=None, ly=None, lsize=11):
        d = ' stroke-dasharray="6 4"' if dash else ''
        ms = ' marker-start="url(#arrR)"' if (both and color == BAD) else (' marker-start="url(#arr)"' if both else '')
        me = ' marker-end="url(#arrR)"' if color == BAD else ' marker-end="url(#arr)"'
        self.add(f'<line x1="{p1[0]}" y1="{p1[1]}" x2="{p2[0]}" y2="{p2[1]}" '
                 f'stroke="{color}" stroke-width="2"{d}{ms}{me}/>')
        if label:
            mx = lx if lx is not None else (p1[0] + p2[0]) / 2
            my = ly if ly is not None else (p1[1] + p2[1]) / 2
            w = len(label) * lsize * 0.6 + 8
            self.add(f'<rect x="{mx-w/2}" y="{my-lsize+1}" width="{w}" height="{lsize+6}" rx="3" fill="{BG}" opacity="0.85"/>')
            self.text(mx, my + 4, label, lsize, MUTED, mono=False)

    def flaw(self, x, y, w, code, text, target=None, sev=BAD):
        h = 18 + 14 * len(text)
        if target:
            self.add(f'<line x1="{x+w/2}" y1="{y}" x2="{target[0]}" y2="{target[1]}" '
                     f'stroke="{sev}" stroke-width="1.4" stroke-dasharray="4 3"/>')
        self.add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="#2a0f0f" stroke="{sev}" stroke-width="1.6"/>')
        self.text(x + 10, y + 16, f"⚠ {code}", 12, sev, "start", weight="bold")
        for i, ln in enumerate(text):
            self.text(x + 10, y + 32 + i * 14, ln, 10.5, "#f0c9c9", "start")
        return Anchor(x, y, w, h)

    def note(self, x, y, w, items, color=OK, title=None):
        h = 16 + 15 * len(items) + (16 if title else 0)
        self.add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{PANEL2}" stroke="{color}" stroke-width="1.4"/>')
        yy = y + 18
        if title:
            self.text(x + 10, yy, title, 12, color, "start", weight="bold"); yy += 18
        for ln in items:
            self.text(x + 10, yy, ln, 10.5, MUTED, "start"); yy += 15

    def render(self, name):
        defs = (
            '<defs>'
            '<marker id="arr" markerWidth="9" markerHeight="9" refX="7.5" refY="3" orient="auto" markerUnits="strokeWidth">'
            f'<path d="M0,0 L7.5,3 L0,6 Z" fill="{ACCENT}"/></marker>'
            '<marker id="arrR" markerWidth="9" markerHeight="9" refX="7.5" refY="3" orient="auto" markerUnits="strokeWidth">'
            f'<path d="M0,0 L7.5,3 L0,6 Z" fill="{BAD}"/></marker>'
            '</defs>'
        )
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" height="{self.h}" '
            f'viewBox="0 0 {self.w} {self.h}">{defs}'
            f'<rect width="{self.w}" height="{self.h}" fill="{BG}"/>'
            f'<text x="28" y="40" fill="{TEXT}" font-family="{FONT}" font-size="22" font-weight="bold">{esc(self.title)}</text>'
            f'<text x="{self.w-28}" y="40" fill="{MUTED}" font-family="{FONT}" font-size="13" text-anchor="end">SATYAMEBA · © Samaraho Mukherjee</text>'
            f'<line x1="28" y1="52" x2="{self.w-28}" y2="52" stroke="{BORDER}"/>'
            + "".join(self.body) + '</svg>'
        )
        svg_path = os.path.join(HERE, f"{name}.svg")
        png_path = os.path.join(HERE, f"{name}.png")
        with open(svg_path, "w") as f:
            f.write(svg)
        cairosvg.svg2png(url=svg_path, write_to=png_path, output_width=self.w * 2)
        print("wrote", svg_path, "+", png_path)


class Diamond:
    def __init__(self, cx, cy, w, h): self.cx, self.cy, self.w, self.h = cx, cy, w, h
    @property
    def top(self): return (self.cx, self.cy - self.h / 2)
    @property
    def bottom(self): return (self.cx, self.cy + self.h / 2)
    @property
    def left(self): return (self.cx - self.w / 2, self.cy)
    @property
    def right(self): return (self.cx + self.w / 2, self.cy)


class Anchor:
    def __init__(self, x, y, w, h): self.x, self.y, self.w, self.h = x, y, w, h
    @property
    def top(self): return (self.x + self.w / 2, self.y)
    @property
    def bottom(self): return (self.x + self.w / 2, self.y + self.h)
    @property
    def left(self): return (self.x, self.y + self.h / 2)
    @property
    def right(self): return (self.x + self.w, self.y + self.h / 2)
    @property
    def center(self): return (self.x + self.w / 2, self.y + self.h / 2)
    def p(self, fx, fy): return (self.x + self.w * fx, self.y + self.h * fy)


LEGEND = ("Legend:  ▭ process   ▱ external entity   ⌑ data store   → data flow   ⚠ flaw (Nn / earlier)")


def legend(c, x, y):
    c.add(f'<rect x="{x}" y="{y}" width="40" height="22" rx="8" fill="{PANEL}" stroke="{BLUE}" stroke-width="2"/>')
    c.text(x + 60, y + 16, "process", 11.5, MUTED, "start")
    c.add(f'<rect x="{x+140}" y="{y}" width="40" height="22" rx="3" fill="{PANEL2}" stroke="{ACCENT}" stroke-width="2"/>')
    c.text(x + 200, y + 16, "external entity", 11.5, MUTED, "start")
    c.add(f'<line x1="{x+320}" y1="{y}" x2="{x+360}" y2="{y}" stroke="{PURPLE}" stroke-width="2.5"/>')
    c.add(f'<line x1="{x+320}" y1="{y+22}" x2="{x+360}" y2="{y+22}" stroke="{PURPLE}" stroke-width="2.5"/>')
    c.text(x + 372, y + 16, "data store", 11.5, MUTED, "start")
    c.add(f'<line x1="{x+470}" y1="{y+11}" x2="{x+520}" y2="{y+11}" stroke="{ACCENT}" stroke-width="2" marker-end="url(#arr)"/>')
    c.text(x + 530, y + 16, "data flow", 11.5, MUTED, "start")
    c.add(f'<rect x="{x+620}" y="{y}" width="20" height="22" rx="5" fill="#2a0f0f" stroke="{BAD}"/>')
    c.text(x + 650, y + 16, "flaw / risk", 11.5, MUTED, "start")


# --------------------------------------------------------------------------- #
def level0():
    c = C(1200, 720, "SATYAMEBA — Level 0 DFD (Context)")
    legend(c, 28, 64)
    sysb = c.box(470, 300, 260, 120, "0", ["SATYAMEBA", "notebook-cloud platform"], stroke=BLUE, tsize=20)
    user = c.entity(90, 150, 200, 80, "User", "grad student / researcher")
    admin = c.entity(90, 470, 200, 80, "Admin", "absolute control")
    worker = c.entity(910, 150, 200, 80, "Worker node agent", "join / heartbeat")
    totp = c.entity(910, 470, 200, 80, "Authenticator app", "offline TOTP, no 3rd party")

    c.flow(user.right, (sysb.x, 330), "register / login / launch", lx=380, ly=300)
    c.flow((sysb.x, 360), (user.x + user.w, user.y + user.h - 10), "notebook URL · SSO · tokens", lx=380, ly=372)
    c.flow(admin.right, (sysb.x, 390), "approve / suspend / reset / delete", lx=380, ly=430)
    c.flow((sysb.x, 408), (admin.x + admin.w, admin.y + 12), "dashboards · live metrics · audit", lx=380, ly=470)
    c.flow(worker.left, (sysb.x + sysb.w, 330), "register / heartbeat (HMAC)", lx=830, ly=300)
    c.flow((sysb.x + sysb.w, 360), (worker.x, worker.y + worker.h - 10), "scheduled notebook", lx=830, ly=372)
    c.flow(totp.left, (sysb.x + sysb.w, 392), "6-digit code (login)", lx=830, ly=455)

    c.note(450, 470, 300, ["Only ports 80/443 are published.",
                           "TLS edge fronts every interaction.",
                           "All data stays on the lab's own metal."], color=OK, title="Boundary")
    c.flaw(450, 600, 300, "N10", ["Schema changes use create_all (no Alembic) —",
                                  "upgrading an EXISTING DB misses new columns."], sev=WARN)
    c.render("dfd_level0")


def level1():
    c = C(1640, 980, "SATYAMEBA — Level 1 DFD (Module-wise overview)")
    legend(c, 28, 64)
    user = c.entity(40, 150, 150, 70, "User")
    admin = c.entity(40, 250, 150, 70, "Admin")
    edge = c.box(260, 180, 180, 110, "1  Edge", ["nginx · TLS", "SPA · reverse proxy", "only 80/443"], stroke=ACCENT)
    gw = c.box(520, 150, 200, 170, "2  Gateway", ["FastAPI + ORM", "auth · admin · nodes", "notebooks · internal", "middleware chain"], stroke=BLUE)
    hub = c.box(800, 150, 180, 120, "3  JupyterHub", ["authenticator + SSO", "Docker/Swarm spawner", "profiles"], stroke=BLUE)
    nb = c.box(1080, 150, 180, 120, "4  Notebook", ["isolated container", "per user", "optional gVisor/GPU"], stroke=OK)
    prom = c.box(800, 560, 180, 90, "5  Prometheus", ["scrape exporters", "instant queries"], stroke=PURPLE)
    graf = c.box(1080, 560, 180, 90, "6  Grafana", ["dashboards", "embedded in admin"], stroke=PURPLE)

    d1 = c.store(520, 420, 200, 46, "D1", "Postgres")
    d2 = c.store(520, 500, 200, 46, "D2", "Redis")
    d3 = c.store(1080, 330, 200, 46, "D3", "user + shared volumes")
    expo = c.entity(560, 700, 320, 60, "Node exporters", "node-exporter · cAdvisor · DCGM (per node)")

    c.flow(user.right, edge.left, "https")
    c.flow(admin.right, (edge.x, 270), "https")
    c.flow(edge.right, gw.left, "/api/*", both=True)
    c.flow((edge.x + edge.w, 250), (hub.x, 250), "/hub /user", both=True, ly=250, lx=735)
    c.flow(gw.bottom, d1.top, "ORM", both=True, lx=620, ly=400)
    c.flow((gw.x + 40, gw.y + gw.h), (d2.x + 40, d2.y), "rate/nonce", both=True, lx=470, ly=490)
    c.flow(gw.right, hub.left, "admin API · internal", both=True, ly=186, lx=762)
    c.flow(hub.right, nb.left, "spawn", lx=1030, ly=200)
    c.flow(nb.bottom, d3.top, "read/write", both=True, lx=1170, ly=310)
    c.flow(expo.top, prom.bottom, "metrics", lx=720, ly=678)
    c.flow((gw.x + gw.w, 300), prom.left, "instant query", lx=760, ly=560)
    c.flow(prom.right, graf.left, "PromQL")
    c.flow(graf.top, (edge.x + edge.w - 20, edge.y + edge.h), "/grafana (iframe)", color=ACCENT, dash=True, lx=900, ly=420)

    # flaw annotations
    c.flaw(300, 560, 250, "F-SPOF", ["D1 single Postgres + single Hub =",
                                     "single points of failure (HA wiring",
                                     "exists; you supply replicated PG)."], target=d1.left, sev=WARN)
    c.flaw(300, 720, 250, "N1", ["Internal secret is overloaded (node",
                                 "HMAC + Hub auth + SSO). Now decoupled",
                                 "from TOTP encryption key (fixed)."], target=gw.bottom, sev=OK)
    c.flaw(1300, 330, 300, "N2/N3 ✓", ["FIXED: storage keyed by a hash of the",
                                       "immutable account id (u-<hash>) — reused",
                                       "usernames can't inherit old files."], target=d3.right, sev=OK)
    c.flaw(1300, 470, 300, "N13", ["SPA logout does not end the Hub",
                                   "session in the other tab (suspend",
                                   "does, via hub.delete_user)."], target=hub.bottom, sev=WARN)
    c.render("dfd_level1")


def level2():
    c = C(1680, 1060, "SATYAMEBA — Level 2 DFD (every module)")
    legend(c, 28, 64)
    # external
    user = c.entity(40, 150, 130, 64, "User")
    admin = c.entity(40, 240, 130, 64, "Admin")
    worker = c.entity(40, 330, 130, 64, "Worker agent")

    # Edge decomposition
    edge = c.box(220, 110, 200, 300, "1  Edge (nginx)", None, stroke=ACCENT)
    c.box(235, 150, 170, 40, "1.1 TLS + headers/CSP", None, stroke=BORDER, fill=PANEL2, rx=6, tsize=11)
    c.box(235, 200, 170, 40, "1.2 SPA static", None, stroke=BORDER, fill=PANEL2, rx=6, tsize=11)
    c.box(235, 250, 170, 40, "1.3 proxy /api /hub", None, stroke=BORDER, fill=PANEL2, rx=6, tsize=11)
    c.box(235, 300, 170, 40, "1.4 block /api/internal", None, stroke=OK, fill=PANEL2, rx=6, tsize=11)
    c.box(235, 350, 170, 40, "1.5 dyn resolver", None, stroke=OK, fill=PANEL2, rx=6, tsize=11)

    # Gateway processes
    mw = c.box(470, 110, 230, 70, "2.0 Middleware chain", ["Hdrs→CORS→Rate→Bot→Sign→Metrics"], stroke=BLUE)
    auth = c.box(470, 210, 230, 90, "2.1 Auth", ["register/login/refresh/logout", "2FA · change-pw"], stroke=BLUE)
    adm = c.box(470, 330, 230, 90, "2.2 Admin", ["approve/reject/suspend", "reset-2fa/pw · delete · metrics"], stroke=BLUE)
    note = c.box(470, 450, 230, 70, "2.3 Notebooks", ["launch (OTT) · stop · status"], stroke=BLUE)
    nodes = c.box(470, 540, 230, 70, "2.4 Nodes", ["register · heartbeat (HMAC)"], stroke=BLUE)
    intern = c.box(470, 630, 230, 70, "2.5 Internal", ["authenticate · redeem-ott"], stroke=BLUE)
    maint = c.box(470, 720, 230, 60, "2.6 Maintenance loop", ["purge tokens/sessions"], stroke=BLUE)

    # stores (D1 tables + redis)
    su = c.store(760, 210, 180, 40, "T1", "users")
    ss = c.store(760, 270, 180, 40, "T2", "sessions")
    so = c.store(760, 330, 180, 40, "T3", "sso_tokens")
    sn = c.store(760, 390, 180, 40, "T4", "nodes")
    sa = c.store(760, 450, 180, 40, "T5", "audit_logs")
    redis = c.store(760, 520, 180, 40, "D2", "redis")

    # Hub decomposition
    hub = c.box(1010, 150, 240, 230, "3  JupyterHub", None, stroke=BLUE)
    hauth = c.box(1025, 195, 210, 50, "3.1 Authenticator", ["pw OR ott → gateway"], stroke=BORDER, fill=PANEL2, rx=6, tsize=11)
    c.box(1025, 255, 210, 50, "3.2 SSO login handler", ["redeem-ott → cookie"], stroke=BORDER, fill=PANEL2, rx=6, tsize=11)
    spawn = c.box(1025, 315, 210, 50, "3.3 Spawner + pre_spawn", ["profile → cpu/mem/gpu"], stroke=BORDER, fill=PANEL2, rx=6, tsize=11)

    nb = c.box(1330, 170, 200, 110, "4  Notebook", ["JupyterLab", "cap_drop=ALL", "gVisor? · GPU?"], stroke=OK)
    vol = c.store(1330, 320, 200, 44, "D3", "work + shared (NFS)")
    prom = c.box(1330, 470, 200, 80, "5  Prometheus", ["dockerswarm SD"], stroke=PURPLE)
    graf = c.box(1330, 600, 200, 70, "6  Grafana", ["dashboards"], stroke=PURPLE)
    expo = c.entity(1010, 470, 250, 60, "Exporters", "node-exporter·cAdvisor·DCGM")

    # flows (external → edge → gateway)
    c.flow(user.right, edge.p(0, 0.25))
    c.flow(admin.right, edge.p(0, 0.5))
    c.flow(worker.right, edge.p(0, 0.8))
    c.flow(edge.right, mw.left, "signed JSON", both=True, ly=150, lx=440)
    for proc in (auth, adm, note, nodes, intern):
        c.flow((mw.x + mw.w / 2, mw.y + mw.h), proc.left, color=BORDER if proc not in (auth,) else ACCENT)
    # gateway ↔ tables
    c.flow(auth.right, su.left, both=True, color=PURPLE)
    c.flow(auth.right, ss.left, both=True, color=PURPLE)
    c.flow(note.right, so.left, both=True, color=PURPLE)
    c.flow(nodes.right, sn.left, both=True, color=PURPLE)
    c.flow(adm.right, sa.left, both=True, color=PURPLE)
    c.flow(mw.bottom, redis.left, "rate/nonce", color=PURPLE, lx=900, ly=540)
    # gateway → hub
    c.flow(note.right, hauth.left, "start + OTT", color=ACCENT, lx=980, ly=470)
    c.flow(intern.right, (hub.x, 230), "verify (internal)", both=True, color=ACCENT, lx=860, ly=650)
    # hub → notebook → vol
    c.flow(spawn.right, nb.left, "spawn", lx=1300, ly=300)
    c.flow(nb.bottom, vol.top, both=True, color=PURPLE)
    # metrics
    c.flow(expo.right, prom.left, "scrape")
    c.flow(prom.bottom, graf.top, "PromQL")
    c.flow(adm.p(1, 0.2), prom.left, "instant query", color=ACCENT, dash=True, lx=1050, ly=430)

    # flaws
    c.flaw(40, 470, 270, "N2/N3", ["delete user → T1 row gone but D3",
                                   "volume + Hub state keyed by username",
                                   "remain → leak / reuse inheritance."], target=vol.left, sev=BAD)
    c.flaw(40, 600, 270, "N9", ["2 gateway replicas race on bootstrap-",
                                "admin insert — now caught (IntegrityError)."], target=su.left, sev=OK)
    c.flaw(40, 700, 270, "N1", ["TOTP secret encrypted at rest; key now",
                                "dedicated (SAT_DATA_ENCRYPTION_KEY)."], target=su.bottom, sev=OK)
    c.flaw(40, 800, 270, "N10", ["No DB migrations (create_all only).",
                                 "Existing-DB upgrades need manual DDL/Alembic."], target=ss.left, sev=WARN)
    c.flaw(1330, 720, 300, "verify", ["nginx variable proxy_pass + resolver:",
                                      "run `nginx -t` / smoke-test on first",
                                      "real deploy (untestable in CI)."], sev=WARN)
    c.render("dfd_level2")


def flowchart():
    c = C(1280, 1240, "SATYAMEBA — User & request lifecycle (flowchart)")

    def node(x, y, w, h, t, sub=None, stroke=BLUE, rx=10):
        return c.box(x, y, w, h, t, sub, stroke=stroke, rx=rx, tsize=13)

    def diamond(cx, cy, w, h, t):
        pts = f"{cx},{cy-h/2} {cx+w/2},{cy} {cx},{cy+h/2} {cx-w/2},{cy}"
        c.add(f'<polygon points="{pts}" fill="{PANEL}" stroke="{WARN}" stroke-width="2"/>')
        c.text(cx, cy + 4, t, 12, TEXT, weight="bold")
        return Diamond(cx, cy, w, h)

    def v(p1, p2, label=None):
        c.flow(p1, p2, label)

    reg = node(540, 80, 200, 50, "Register", "status = pending", stroke=ACCENT)
    appr = diamond(640, 200, 200, 70, "Admin approves?")
    rej = node(900, 175, 180, 50, "Rejected / waits", stroke=BAD)
    login = node(540, 290, 200, 50, "Login (password)")
    lock = diamond(640, 400, 210, 70, "pwd ok & not locked?")
    fail = node(900, 375, 180, 50, "401 · lockout after 5", stroke=BAD)
    twofa = diamond(640, 540, 200, 76, "2FA enabled?")
    otp = node(900, 515, 180, 50, "Require 6-digit OTP", stroke=PURPLE)
    mustc = diamond(640, 690, 230, 76, "must_change_pw?")
    chg = node(900, 665, 180, 50, "Force change-pw", stroke=WARN)
    issue = node(540, 820, 200, 54, "Issue JWT + signing key", stroke=OK)
    launch = node(540, 920, 200, 54, "Launch (pick profile)")
    ott = node(540, 1010, 200, 54, "Gateway: start server + OTT")
    sso = node(280, 1010, 200, 54, "Open /hub/sso-login", stroke=ACCENT)
    redeem = node(40, 920, 200, 54, "Hub redeems OTT → cookie", stroke=ACCENT)
    sched = node(40, 820, 200, 54, "Swarm schedules on free node", stroke=OK)
    lab = node(40, 720, 200, 54, "JupyterLab (NFS /work)", stroke=OK)

    v(reg.bottom, (640, 165))
    v((740, 200), rej.left, "no")
    v((640, 235), login.top, "yes")
    v(login.bottom, (640, 365))
    v((745, 400), fail.left, "no")
    v((640, 435), twofa.top, "yes")
    v((740, 540), otp.left, "yes")
    v(otp.bottom, (820, 600))
    v((640, 578), mustc.top, "no →")
    v((755, 690), chg.left, "yes")
    v(chg.bottom, (820, 760))
    v((640, 728), issue.top, "no")
    v(issue.bottom, launch.top)
    v(launch.bottom, ott.top)
    v(ott.left, sso.right)
    v(sso.top, (300, 1010), None)
    v((280, 1010), redeem.p(0.7, 1.0), "new tab")
    v(redeem.top, sched.bottom)
    v(sched.top, lab.bottom)

    c.note(820, 880, 380, [
        "Every state-changing API call additionally passes:",
        "TLS edge → SecurityHeaders → CORS → RateLimit →",
        "BotFilter → RequestSigning(HMAC+nonce) → handler.",
        "Suspend/delete instantly revoke sessions + Hub server.",
    ], color=BLUE, title="Per-request security path")
    c.flaw(820, 1040, 380, "N13", ["SPA logout ends the SPA session but not the",
                                   "Hub cookie/notebook in the other tab."], sev=WARN)
    c.render("flowchart")


def owner_control():
    c = C(1480, 900, "SATYAMEBA — Owner break-glass & tamper control plane")
    legend(c, 28, 64)

    owner = c.entity(40, 150, 200, 90, "Owner (you)", ["laptop / phone", "Samaraho Mukherjee"])
    ts = c.box(330, 150, 220, 90, "Tailscale", ["WireGuard mesh", "outbound-only · SSO · ACL"], stroke=ACCENT)
    master = c.box(640, 130, 200, 130, "Master", ["gateway · db · hub", "tailscaled --ssh", "watchdog + keystore"], stroke=BLUE)
    w = []
    for i in range(3):
        w.append(c.box(900 + i * 190, 130, 170, 90, f"Worker {i+1}", ["tailscaled --ssh", "notebooks"], stroke=OK))

    c.flow(owner.right, ts.left, "SSH (super-user)", both=True, dash=True, color=OK, lx=290, ly=180)
    c.flow(ts.right, master.left, "outbound", both=True, dash=True, color=OK, lx=600, ly=180)
    for wb in w:
        c.flow(ts.p(0.7, 1.0), wb.bottom, color=OK, dash=True)

    # Owner role + watchdog logic on the master
    d1 = c.store(640, 320, 200, 44, "T1", "users (role=owner)")
    keystore = c.store(640, 400, 200, 44, "K", "keystore (root KEK)")
    d3 = c.store(900, 320, 250, 44, "D3", "u-<hash> encrypted store")

    wd = c.box(360, 360, 220, 110, "Watchdog", ["every 2 min", "owner present? tailscale up?"], stroke=WARN)
    c.flow(wd.right, d1.left, "check", lx=610, ly=345)
    c.flow(master.bottom, d1.top, color=PURPLE)
    c.flow(master.bottom, keystore.top, color=PURPLE, lx=720, ly=300)
    c.flow((900, 200), d3.top, "spawn → mount", lx=980, ly=290)

    seal = c.box(360, 520, 150, 56, "SEAL", ["halt + lock + alert"], stroke=ACCENT)
    wipe = c.box(560, 520, 200, 56, "CRYPTO-ERASE", ["shred KEK → ciphertext"], stroke=BAD)
    c.flow(wd.bottom, seal.top, "tamper", color=BAD, lx=420, ly=500)
    c.flow(seal.right, wipe.left, "armed + grace exceeded", color=BAD, lx=535, ly=508)
    c.flow(wipe.right, keystore.bottom, "destroys", color=BAD, dash=True, lx=640, ly=500)

    c.note(800, 470, 380, [
        "Separate control plane from the app: a hostile co-admin",
        "demoting you in SATYAMEBA can't touch Tailscale or the",
        "un-removable Owner role. Seal is reversible; wipe is not.",
    ], color=BLUE, title="Why it survives takeover")
    c.flaw(800, 600, 380, "F1 ✓", ["FIXED: startup ensures the Postgres 'owner'",
                                   "enum value exists (create_all can't migrate it)."], sev=OK)
    c.flaw(800, 680, 380, "F2 ✓", ["FIXED: watchdog seals/alerts once per tamper",
                                   "transition (no per-tick spam)."], sev=OK)
    c.flaw(360, 620, 410, "limits", ["Running notebooks/processes need plaintext (root on a",
                                     "node can read live data/code). gocryptfs mount is the",
                                     "remaining wiring. Physical: LUKS/BIOS/TPM/locked rack."], sev=WARN)
    c.render("owner_control")


if __name__ == "__main__":
    level0()
    level1()
    level2()
    flowchart()
    owner_control()
    print("done")
