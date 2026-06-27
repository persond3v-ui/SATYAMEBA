"""Shared visual theme + helper mobjects for the SATYAMEBA Manim tutorials.

Kept LaTeX-free (uses Text, not Tex) so it renders with only ffmpeg + manim —
no TeX install required. Brand colours mirror the web app.
"""
from __future__ import annotations

import os

from manim import (
    DOWN, LEFT, ORIGIN, RIGHT, UP,
    Dot, RoundedRectangle, SVGMobject, Square, Text, VGroup,
)

# --- brand palette ---------------------------------------------------------
BG = "#0e1116"
PANEL = "#161b22"
PANEL2 = "#1c232d"
BORDER = "#2a323d"
TEXT = "#e6edf3"
MUTED = "#8b949e"
ACCENT = "#f5a623"
BLUE = "#4c8dff"
OK = "#3fb950"
BAD = "#f85149"
WARN = "#d29922"

ASSETS = os.path.join(os.path.dirname(__file__), "assets")
MONO = "monospace"


def load_svg(name: str, height: float = 1.0, color: str | None = None):
    """Load an SVG asset, falling back to a simple square if it can't be read."""
    path = os.path.join(ASSETS, f"{name}.svg")
    try:
        m = SVGMobject(path)
        m.set_height(height)
        if color:
            m.set_color(color)
        return m
    except Exception:
        sq = Square(side_length=height).set_stroke(ACCENT, width=3)
        return sq


def label(text: str, size: int = 28, color: str = TEXT, bold: bool = False):
    return Text(text, font_size=size, color=color, weight="BOLD" if bold else "NORMAL")


def code_block(lines, font_size: int = 24):
    """A terminal-style code block from monospaced Text (no LaTeX)."""
    body = VGroup(*[
        Text(ln if ln else " ", font=MONO, font_size=font_size, color=TEXT)
        for ln in lines
    ]).arrange(DOWN, aligned_edge=LEFT, buff=0.16)
    pad, topbar = 0.4, 0.5
    box = RoundedRectangle(
        corner_radius=0.12,
        width=max(body.width + pad * 2, 3.0),
        height=body.height + pad * 2 + topbar,
        fill_color=PANEL2, fill_opacity=1.0, stroke_color=BORDER, stroke_width=1.5,
    ).move_to(ORIGIN)
    dots = VGroup(*[Dot(radius=0.05, color=c) for c in (BAD, ACCENT, OK)]).arrange(RIGHT, buff=0.12)
    dots.next_to(box.get_top(), DOWN, buff=0.18).align_to(box, LEFT).shift(RIGHT * 0.3)
    body.next_to(dots, DOWN, buff=0.2).align_to(box, LEFT).shift(RIGHT * pad)
    return VGroup(box, dots, body)


def pill(text: str, fill: str = ACCENT, fg: str = "#1a1205", width: float = 1.7):
    box = RoundedRectangle(corner_radius=0.14, width=width, height=0.5,
                           fill_color=fill, fill_opacity=1.0, stroke_width=0)
    t = Text(text, font_size=22, color=fg, weight="BOLD").move_to(box)
    return VGroup(box, t)


def step_title(n: int, text: str):
    p = pill(f"STEP {n}")
    t = label(text, size=34, bold=True)
    return VGroup(p, t).arrange(RIGHT, buff=0.4)


def bullet(text: str, color: str = OK, size: int = 26):
    dot = Dot(radius=0.07, color=color)
    return VGroup(dot, label(text, size=size)).arrange(RIGHT, buff=0.25)


def node_box(name: str, sub: str = "", icon: str = "server", accent: str = BLUE,
             w: float = 2.3, h: float = 1.7):
    box = RoundedRectangle(corner_radius=0.15, width=w, height=h,
                           fill_color=PANEL, fill_opacity=1.0,
                           stroke_color=accent, stroke_width=2.5)
    ic = load_svg(icon, height=0.55, color=accent)
    parts = [ic, label(name, size=24, bold=True)]
    if sub:
        parts.append(label(sub, size=18, color=MUTED))
    inner = VGroup(*parts).arrange(DOWN, buff=0.1).move_to(box)
    return VGroup(box, inner)


def footer():
    return label("SATYAMEBA  ·  © Samaraho Mukherjee", size=18, color=MUTED)
