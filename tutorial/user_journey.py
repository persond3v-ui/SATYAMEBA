"""SATYAMEBA — User journey tutorial (Manim Community Edition).

The end-user experience: register, get approved, launch an isolated GPU
notebook, work, and never lose your data.

    manim -qh tutorial/user_journey.py            # render every scene
    manim -qh tutorial/user_journey.py Launch     # one scene

Scenes: UserIntro, Register, Launch, Workspace, Persistence, UserSecurity, UserOutro.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from manim import *  # noqa: F401,F403
from theme import (  # noqa: E402
    ACCENT, BAD, BG, BLUE, BORDER, MUTED, OK, PANEL, PANEL2, TEXT, WARN,
    bullet, code_block, footer, label, load_svg, node_box, pill,
)


class _Base(Scene):
    def setup(self):
        self.camera.background_color = BG

    def banner(self, text, fill=ACCENT, fg="#1a1205"):
        head = VGroup(pill("YOU", fill=fill, fg=fg, width=1.2),
                      label(text, size=34, bold=True)).arrange(RIGHT, buff=0.4).to_edge(UP, buff=0.7)
        self.play(FadeIn(head[0], scale=0.8), Write(head[1]))
        return head


class UserIntro(_Base):
    def construct(self):
        person = load_svg("user", height=1.6, color=ACCENT)
        name = label("Meera — grad student", size=34, bold=True)
        g = VGroup(person, name).arrange(DOWN, buff=0.3)
        self.play(FadeIn(person, scale=0.6), Write(name))
        self.wait(0.5)
        pains = VGroup(
            bullet("SSH into 'the GPU box' and hope it's free", color=WARN),
            bullet("Re-build my conda env for the 100th time", color=WARN),
            bullet("Once rm -rf'd a labmate's data", color=BAD),
            bullet("Colab keeps disconnecting — and no RTX 5070", color=BAD),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.3)
        self.play(g.animate.to_edge(UP, buff=1.0).scale(0.8))
        self.play(LaggedStart(*[FadeIn(p, shift=RIGHT) for p in pains], lag_ratio=0.35))
        self.wait(1.5)
        self.play(FadeOut(pains), FadeOut(g))


class Register(_Base):
    def construct(self):
        head = self.banner("1 · Register & get approved")
        card = RoundedRectangle(corner_radius=0.15, width=5, height=4.2,
                                fill_color=PANEL, fill_opacity=1, stroke_color=BORDER)
        card.next_to(head, DOWN, buff=0.5).to_edge(LEFT, buff=1.2)
        title = label("Request access", size=26, bold=True).move_to(card.get_top()).shift(DOWN * 0.5)
        fields = VGroup(*[
            RoundedRectangle(corner_radius=0.08, width=4, height=0.55,
                             fill_color=PANEL2, fill_opacity=1, stroke_color=BORDER)
            for _ in range(3)
        ]).arrange(DOWN, buff=0.3).move_to(card).shift(DOWN * 0.2)
        btn = pill("Submit request", fill=ACCENT, width=3).next_to(fields, DOWN, buff=0.4)
        self.play(Create(card), Write(title))
        self.play(LaggedStart(*[FadeIn(f) for f in fields], lag_ratio=0.2), FadeIn(btn))

        # status flow: pending -> approved
        flow = VGroup(
            pill("pending", fill="#3a2d0a", fg=WARN, width=2.2),
            label("→", size=40, color=MUTED),
            pill("admin approves", fill=PANEL, fg=TEXT, width=3.2),
            label("→", size=40, color=MUTED),
            pill("approved", fill="#0c2a14", fg=OK, width=2.2),
        ).arrange(RIGHT, buff=0.3).scale(0.8)
        flow.to_edge(RIGHT, buff=0.8).shift(UP * 0.2)
        flow[2][0].set_stroke(BORDER, width=1.5)
        self.play(LaggedStart(*[FadeIn(f, shift=UP) for f in flow], lag_ratio=0.3))
        self.play(Indicate(flow[4], color=OK))
        self.wait(1.5)
        self.play(FadeOut(Group(*self.mobjects)))


class Launch(_Base):
    def construct(self):
        head = self.banner("2 · Launch a notebook")
        profiles = VGroup(
            pill("Small · 2GB · 1 CPU", fill=PANEL, fg=TEXT, width=3.6),
            pill("Medium · 4GB · 2 CPU", fill=PANEL, fg=TEXT, width=3.8),
            pill("GPU · 8GB · 4 CPU · 1 GPU", fill=ACCENT, width=4.6),
        ).arrange(DOWN, buff=0.3).scale(0.95)
        profiles.next_to(head, DOWN, buff=0.5).to_edge(LEFT, buff=1.0)
        for p in profiles[:2]:
            p[0].set_stroke(BORDER, width=1.5)
        self.play(LaggedStart(*[FadeIn(p, shift=RIGHT) for p in profiles], lag_ratio=0.25))
        self.play(Indicate(profiles[2], color=ACCENT))
        launch = pill("Launch  >>  (new tab)", fill=OK, fg="#06210d", width=4.2)
        launch.next_to(profiles, DOWN, buff=0.5).align_to(profiles, LEFT)
        self.play(FadeIn(launch, scale=0.9), Flash(launch, color=OK, line_length=0.25))

        # scheduler places it on a free node
        nodes = VGroup(*[
            node_box(f"node {i}", "", "gpu", BORDER, w=1.6, h=1.1).scale(0.85)
            for i in range(1, 5)
        ]).arrange(RIGHT, buff=0.3).to_edge(RIGHT, buff=0.7).shift(UP * 0.5)
        self.play(LaggedStart(*[FadeIn(n) for n in nodes], lag_ratio=0.15))
        nb = load_svg("notebook", height=0.7).move_to(launch).shift(UP * 0.1)
        target = nodes[2]
        self.play(nb.animate.move_to(target.get_center()), run_time=1.2)
        self.play(target[0].animate.set_stroke(OK, width=3),
                  Flash(target, color=OK, line_length=0.2))
        sso = label("SSO — no second login. JupyterLab opens.", size=24, color=BLUE)
        sso.next_to(nodes, DOWN, buff=0.6)
        self.play(FadeIn(sso, shift=UP))
        self.wait(1.5)
        self.play(FadeOut(Group(*self.mobjects)))


class Workspace(_Base):
    def construct(self):
        head = self.banner("3 · Work — like Colab, but yours")
        lab = RoundedRectangle(corner_radius=0.12, width=11, height=5,
                               fill_color=PANEL, fill_opacity=1, stroke_color=BORDER)
        lab.next_to(head, DOWN, buff=0.4)
        nb = load_svg("notebook", height=2.0).move_to(lab).shift(LEFT * 3.5)
        cells = code_block([
            "import torch",
            "model = MyNet().cuda()   # RTX 5070",
            "train(model, data)       # training...",
        ], font_size=22).scale(0.8).move_to(lab).shift(RIGHT * 1.8 + UP * 0.4)
        self.play(Create(lab))
        self.play(FadeIn(nb, shift=RIGHT), FadeIn(cells, shift=LEFT))
        feats = VGroup(
            bullet("Upload datasets — no size cap → /work", color=OK),
            bullet("Shared datasets in /shared", color=BLUE),
            bullet("Fully isolated — can't touch anyone else", color=ACCENT),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.22).scale(0.8)
        feats.next_to(cells, DOWN, buff=0.4).align_to(cells, LEFT)
        self.play(LaggedStart(*[FadeIn(f, shift=RIGHT) for f in feats], lag_ratio=0.3))
        self.wait(2)
        self.play(FadeOut(Group(*self.mobjects)))


class Persistence(_Base):
    def construct(self):
        head = self.banner("4 · Your work is always there")
        clock = VGroup(
            Circle(radius=0.6, color=MUTED, stroke_width=3),
            Line(ORIGIN, UP * 0.4, color=MUTED), Line(ORIGIN, RIGHT * 0.3, color=MUTED),
        )
        clock.next_to(head, DOWN, buff=0.5)
        cull = label("idle 1h → container reclaimed", size=24, color=WARN).next_to(clock, RIGHT, buff=0.4)
        self.play(Create(clock[0]), Create(clock[1]), Create(clock[2]), FadeIn(cull))
        safe = label("…but your files stay in your volume.", size=26, color=OK)
        safe.next_to(clock, DOWN, buff=0.6)
        self.play(Write(safe))

        # NFS: relaunch lands on a different node, data follows
        n1 = node_box("node 2", "", "gpu", BORDER, w=1.8, h=1.2).shift(LEFT * 3 + DOWN * 1.5)
        n2 = node_box("node 4", "", "gpu", OK, w=1.8, h=1.2).shift(RIGHT * 3 + DOWN * 1.5)
        store = RoundedRectangle(corner_radius=0.1, width=2.4, height=0.9,
                                 fill_color=PANEL, fill_opacity=1, stroke_color=ACCENT)
        store_l = label("NFS /work", size=20, color=ACCENT).move_to(store)
        store_g = VGroup(store, store_l).next_to(VGroup(n1, n2), DOWN, buff=0.5)
        self.play(FadeIn(n1), FadeIn(n2), FadeIn(store_g))
        a1 = Arrow(store.get_top(), n1.get_bottom(), buff=0.1, color=BORDER, stroke_width=3)
        a2 = Arrow(store.get_top(), n2.get_bottom(), buff=0.1, color=OK, stroke_width=3)
        self.play(GrowArrow(a1), GrowArrow(a2))
        follow = label("Relaunch on any node — same data follows you.",
                       size=24, color=BLUE).next_to(store_g, DOWN, buff=0.4)
        self.play(FadeIn(follow, shift=UP))
        self.wait(2)
        self.play(FadeOut(Group(*self.mobjects)))


class UserSecurity(_Base):
    def construct(self):
        head = self.banner("5 · Protect your account", fill=OK, fg="#06210d")
        lock = load_svg("lock", height=1.8, color=ACCENT).next_to(head, DOWN, buff=0.5)
        self.play(FadeIn(lock, scale=0.6))
        qr = VGroup()
        for r in range(5):
            for c in range(5):
                if (r + c) % 2 == 0 or (r * c) % 3 == 0:
                    qr.add(Square(side_length=0.16, fill_color=TEXT, fill_opacity=1,
                                  stroke_width=0).move_to([c * 0.16, -r * 0.16, 0]))
        qr.move_to(lock).shift(RIGHT * 3)
        qr_bg = RoundedRectangle(corner_radius=0.08, width=1.3, height=1.3,
                                 fill_color="#ffffff", fill_opacity=1, stroke_width=0).move_to(qr)
        self.play(FadeIn(qr_bg), FadeIn(qr))
        steps = VGroup(
            bullet("Scan the QR with any authenticator app"),
            bullet("Works fully offline — no third-party service", color=BLUE),
            bullet("Login now asks for a 6-digit code", color=ACCENT),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.26).next_to(lock, DOWN, buff=0.6)
        self.play(LaggedStart(*[FadeIn(s, shift=RIGHT) for s in steps], lag_ratio=0.3))
        self.wait(2)
        self.play(FadeOut(Group(*self.mobjects)))


class UserOutro(_Base):
    def construct(self):
        person = load_svg("user", height=1.2, color=ACCENT)
        msg = label("No SSH. No setup. No lost work.", size=38, bold=True)
        msg2 = label("Just open your browser and build.", size=30, color=MUTED)
        g = VGroup(person, msg, msg2).arrange(DOWN, buff=0.35)
        self.play(FadeIn(person, scale=0.6), Write(msg))
        self.play(FadeIn(msg2, shift=UP))
        self.play(FadeIn(footer().next_to(g, DOWN, buff=0.6)))
        self.wait(2)
