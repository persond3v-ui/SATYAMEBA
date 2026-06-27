"""SATYAMEBA — Admin / Developer setup tutorial (Manim Community Edition).

Renders a step-by-step guide to standing the platform up across 4 Debian nodes.

    manim -qh tutorial/admin_setup.py            # render every scene
    manim -qh tutorial/admin_setup.py Architecture   # one scene

Scenes (in order): AdminIntro, Architecture, Step1Wizard, Step2Master,
Step3Workers, Step4Dashboard, Step5Security, AdminOutro.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from manim import *  # noqa: F401,F403
from theme import (  # noqa: E402
    ACCENT, BAD, BG, BLUE, BORDER, MUTED, OK, PANEL, TEXT, WARN,
    bullet, code_block, footer, label, load_svg, node_box, pill, step_title,
)


class _Base(Scene):
    def setup(self):
        self.camera.background_color = BG

    def show_title(self, p, t):
        head = VGroup(p, t).arrange(RIGHT, buff=0.4).to_edge(UP, buff=0.7)
        self.play(FadeIn(p, scale=0.8), Write(t))
        return head


class AdminIntro(_Base):
    def construct(self):
        logo = load_svg("logo", height=1.6)
        title = label("SATYAMEBA", size=64, bold=True)
        sub = label("Self-hosted notebook cloud — Admin Setup Guide", size=30, color=MUTED)
        owner = footer()
        group = VGroup(logo, title, sub).arrange(DOWN, buff=0.35)
        self.play(FadeIn(logo, scale=0.6))
        self.play(Write(title))
        self.play(FadeIn(sub, shift=UP))
        self.play(FadeIn(owner.next_to(group, DOWN, buff=0.6)))
        self.wait(1.5)
        problem = VGroup(
            bullet("4 Debian desktops · i7 · RTX 5070", color=BLUE),
            bullet("Students fighting over SSH and GPUs", color=WARN),
            bullet("Clobbered envs, lost work, full disks", color=BAD),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.3)
        self.play(FadeOut(group), FadeOut(owner))
        self.play(LaggedStart(*[FadeIn(b, shift=RIGHT) for b in problem], lag_ratio=0.4))
        self.wait(1)
        goal = label("Goal: Colab, on your own metal.", size=34, color=ACCENT, bold=True)
        self.play(FadeOut(problem), Write(goal))
        self.wait(1.5)
        self.play(FadeOut(goal))


class Architecture(_Base):
    def construct(self):
        head = self.show_title(pill("OVERVIEW", fill=BLUE, fg="#06121f"),
                               label("How the cluster fits together", size=34, bold=True))
        master = node_box("master", "swarm manager", "server", ACCENT).scale(0.95)
        master.next_to(head, DOWN, buff=0.8)
        edge = pill("edge :443", fill=PANEL, fg=TEXT, width=2.0).scale(0.9)
        edge[0].set_stroke(ACCENT, width=2)
        edge.next_to(master, RIGHT, buff=0.6)

        workers = VGroup(*[
            node_box(f"node {i}", "worker · gpu", "gpu", OK, w=2.1, h=1.5).scale(0.9)
            for i in range(1, 5)
        ]).arrange(RIGHT, buff=0.45).to_edge(DOWN, buff=1.0)

        self.play(FadeIn(master, shift=DOWN), FadeIn(edge, shift=DOWN))
        self.play(LaggedStart(*[FadeIn(w, shift=UP) for w in workers], lag_ratio=0.2))
        arrows = VGroup(*[
            Arrow(master.get_bottom(), w.get_top(), buff=0.15,
                  stroke_width=3, color=BORDER, max_tip_length_to_length_ratio=0.08)
            for w in workers
        ])
        self.play(LaggedStart(*[GrowArrow(a) for a in arrows], lag_ratio=0.15))
        vlan = label("same VLAN  ·  swarm join on :2377", size=22, color=MUTED)
        vlan.next_to(workers, UP, buff=0.25)
        self.play(FadeIn(vlan))
        note = label("Only ports 80 / 443 are exposed — everything else is internal.",
                     size=24, color=ACCENT)
        note.next_to(head, DOWN, buff=0.2)
        self.play(FadeIn(note))
        self.wait(2)
        self.play(*[FadeOut(m) for m in [head, master, edge, workers, arrows, vlan, note]])


class Step1Wizard(_Base):
    def construct(self):
        head = self.show_title(pill("STEP 1"),
                               label("Run the setup wizard on every node", size=34, bold=True))
        cmd = code_block([
            "sudo apt-get install -y python3-tk",
            "sudo python3 setup/satyameba_setup.py",
        ], font_size=26).scale(0.95)
        cmd.next_to(head, DOWN, buff=0.6).to_edge(LEFT, buff=1.0)
        self.play(FadeIn(cmd, shift=UP))
        checks = VGroup(
            bullet("Checks Docker, Compose, NVIDIA driver + toolkit"),
            bullet("Installs / fixes whatever is missing"),
            bullet("Verifies GPU passthrough into a test container"),
            bullet("Scan storage & resources → sizes .env to the host", color=ACCENT),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.28)
        checks.next_to(cmd, DOWN, buff=0.5).to_edge(LEFT, buff=1.0)
        self.play(LaggedStart(*[FadeIn(c, shift=RIGHT) for c in checks], lag_ratio=0.3))
        gpu = load_svg("gpu", height=1.6, color=OK).to_edge(RIGHT, buff=1.5).shift(UP * 0.3)
        ok = label("✓ GPU visible", size=24, color=OK).next_to(gpu, DOWN)
        self.play(FadeIn(gpu, scale=0.6))
        self.play(Flash(gpu, color=OK, line_length=0.3), Write(ok))
        self.wait(1.5)
        self.play(*[FadeOut(m) for m in [head, cmd, checks, gpu, ok]])


class Step2Master(_Base):
    def construct(self):
        head = self.show_title(pill("STEP 2"),
                               label("Bring up the master", size=34, bold=True))
        cmd = code_block([
            "./setup/master_init.sh \\",
            "    --advertise-addr 192.168.1.10 \\",
            "    --gpu --nfs --users 16",
        ], font_size=26)
        cmd.next_to(head, DOWN, buff=0.55)
        self.play(FadeIn(cmd, shift=UP))
        does = VGroup(
            bullet("Generates secrets: RSA JWT keypair + TLS cert"),
            bullet("docker swarm init  → becomes the manager"),
            bullet("Sets up NFS so user work follows them across nodes", color=ACCENT),
            bullet("Configures the GPU runtime for Swarm"),
            bullet("Builds images & deploys the whole stack"),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.26)
        does.next_to(cmd, DOWN, buff=0.45)
        self.play(LaggedStart(*[FadeIn(b, shift=RIGHT) for b in does], lag_ratio=0.25))
        self.wait(1.5)
        self.play(*[FadeOut(m) for m in [head, cmd, does]])


class Step3Workers(_Base):
    def construct(self):
        head = self.show_title(pill("STEP 3"),
                               label("Join the 3 worker nodes", size=34, bold=True))
        cmd = code_block([
            "sudo ./setup/worker_join.sh \\",
            "    --master-ip 192.168.1.10 \\",
            "    --join-token SWMTKN-1-xxxx \\",
            "    --node-secret <secret> \\",
            "    --gateway https://192.168.1.10 \\",
            "    --gpu --nfs-server 192.168.1.10",
        ], font_size=22).scale(0.95)
        cmd.next_to(head, DOWN, buff=0.45).to_edge(LEFT, buff=0.8)
        self.play(FadeIn(cmd, shift=UP))
        master = node_box("master", "", "server", ACCENT, w=1.8, h=1.2).scale(0.8)
        master.to_edge(RIGHT, buff=2.2).shift(UP * 1.6)
        workers = VGroup(*[
            node_box(f"node {i}", "", "gpu", BORDER, w=1.5, h=1.0).scale(0.8)
            for i in range(1, 4)
        ]).arrange(DOWN, buff=0.3).next_to(master, DOWN, buff=0.8)
        self.play(FadeIn(master))
        self.play(LaggedStart(*[FadeIn(w) for w in workers], lag_ratio=0.2))
        # workers light up green as they join + register
        joins = []
        for w in workers:
            joins.append(w[0].animate.set_stroke(OK, width=3))
            joins.append(GrowArrow(Arrow(master.get_bottom(), w.get_top(),
                         buff=0.1, color=OK, stroke_width=3)))
        self.play(LaggedStart(*joins, lag_ratio=0.25))
        reg = label("→ appears in Admin · Nodes (online + heartbeat)",
                    size=22, color=OK).next_to(cmd, DOWN, buff=0.5).to_edge(LEFT, buff=0.8)
        self.play(FadeIn(reg, shift=UP))
        self.wait(1.5)
        self.play(FadeOut(Group(*self.mobjects)))


class Step4Dashboard(_Base):
    def construct(self):
        head = self.show_title(pill("STEP 4"),
                               label("Run the cluster from the dashboard", size=32, bold=True))
        browser = RoundedRectangle(corner_radius=0.12, width=11, height=5.2,
                                   fill_color=PANEL, fill_opacity=1, stroke_color=BORDER)
        browser.next_to(head, DOWN, buff=0.4)
        bar = Line(browser.get_corner(UL), browser.get_corner(UR),
                   color=BORDER).shift(DOWN * 0.6)
        url = label("https://satyameba.local", size=20, color=MUTED)
        url.move_to(browser.get_top()).shift(DOWN * 0.35)
        self.play(Create(browser), Create(bar), FadeIn(url))
        tabs = VGroup(
            pill("Approvals", fill=ACCENT, width=1.9),
            pill("Users", fill=PANEL, fg=TEXT, width=1.4),
            pill("Nodes", fill=PANEL, fg=TEXT, width=1.4),
            pill("Monitoring", fill=PANEL, fg=TEXT, width=2.1),
            pill("Audit", fill=PANEL, fg=TEXT, width=1.4),
        ).arrange(RIGHT, buff=0.25).scale(0.85)
        tabs.next_to(bar, DOWN, buff=0.3)
        for p in tabs[1:]:
            p[0].set_stroke(BORDER, width=1.5)
        self.play(LaggedStart(*[FadeIn(t, shift=DOWN) for t in tabs], lag_ratio=0.15))
        actions = VGroup(
            bullet("Approve / reject new members", color=OK),
            bullet("Live CPU / GPU / disk / net — straight from Prometheus", color=BLUE),
            bullet("See running notebooks; kick a user off instantly", color=WARN),
            bullet("Tamper-evident audit log of every action", color=ACCENT),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.24).scale(0.9)
        actions.next_to(tabs, DOWN, buff=0.4)
        self.play(LaggedStart(*[FadeIn(a, shift=RIGHT) for a in actions], lag_ratio=0.3))
        self.wait(2)
        self.play(*[FadeOut(m) for m in [head, browser, bar, url, tabs, actions]])


class Step5Security(_Base):
    def construct(self):
        head = self.show_title(pill("SECURE", fill=OK, fg="#06210d"),
                               label("Hardened by default", size=34, bold=True))
        lock = load_svg("lock", height=1.8, color=ACCENT).next_to(head, DOWN, buff=0.5)
        self.play(FadeIn(lock, scale=0.6), Flash(lock, color=ACCENT, line_length=0.3))
        feats = VGroup(
            bullet("TLS-only edge · just ports 80/443"),
            bullet("Approval gate + admin 2FA (TOTP, no 3rd party)"),
            bullet("Isolated notebooks · optional gVisor sandbox"),
            bullet("RS256 tokens + per-request HMAC signing"),
            bullet("ORM-only DB · tamper-evident audit chain"),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.26)
        feats.next_to(lock, DOWN, buff=0.5)
        self.play(LaggedStart(*[FadeIn(f, shift=RIGHT) for f in feats], lag_ratio=0.25))
        self.wait(2)
        self.play(FadeOut(head), FadeOut(lock), FadeOut(feats))


class AdminOutro(_Base):
    def construct(self):
        logo = load_svg("logo", height=1.3)
        done = label("Your lab is now a notebook cloud.", size=40, bold=True)
        tip = label("make help  ·  docs/DEPLOYMENT.md  ·  docs/SECURITY.md",
                    size=24, color=MUTED)
        g = VGroup(logo, done, tip).arrange(DOWN, buff=0.4)
        self.play(FadeIn(logo, scale=0.6), Write(done))
        self.play(FadeIn(tip, shift=UP))
        self.play(FadeIn(footer().next_to(g, DOWN, buff=0.6)))
        self.wait(2)
