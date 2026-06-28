#!/usr/bin/env python3
"""SATYAMEBA setup wizard.

A tkinter GUI that:
  * checks every host dependency (Docker, Compose v2, NVIDIA driver + Container
    Toolkit, openssl, curl, git, …) with live progress bars,
  * installs / fixes whatever is missing on Debian (apt + NVIDIA repos),
  * verifies GPU passthrough into a throwaway container,
  * then bootstraps the node as MASTER or WORKER for you.

Run it with privileges so it can apt-install and touch the docker group:

    sudo python3 setup/satyameba_setup.py

If tkinter is missing, install it first:  sudo apt-get install -y python3-tk
Owner: Samaraho Mukherjee.
"""
from __future__ import annotations

import os
import queue
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path

try:
    import tkinter as tk
    from tkinter import ttk, messagebox, simpledialog
except Exception:  # pragma: no cover
    sys.stderr.write(
        "tkinter is not available. Install it with:\n"
        "    sudo apt-get install -y python3-tk\n"
    )
    sys.exit(1)

REPO_ROOT = Path(__file__).resolve().parent.parent
IS_ROOT = os.geteuid() == 0
SUDO = [] if IS_ROOT else ["sudo"]


# --------------------------------------------------------------------------- #
# Dependency model
# --------------------------------------------------------------------------- #
@dataclass
class Dependency:
    key: str
    name: str
    check: list[str]                       # command whose 0 exit == present
    install: list[list[str]] = field(default_factory=list)  # ordered fix steps
    required: bool = True
    note: str = ""
    status: str = "unknown"                # unknown | ok | missing | error


def _docker_repo_steps() -> list[list[str]]:
    # Official Docker CE on Debian (idempotent).
    return [
        SUDO + ["install", "-m", "0755", "-d", "/etc/apt/keyrings"],
        ["bash", "-c",
         "curl -fsSL https://download.docker.com/linux/debian/gpg | "
         + ("" if IS_ROOT else "sudo ")
         + "gpg --dearmor -o /etc/apt/keyrings/docker.gpg --yes"],
        SUDO + ["chmod", "a+r", "/etc/apt/keyrings/docker.gpg"],
        ["bash", "-c",
         'echo "deb [arch=$(dpkg --print-architecture) '
         'signed-by=/etc/apt/keyrings/docker.gpg] '
         'https://download.docker.com/linux/debian $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | '
         + ("" if IS_ROOT else "sudo ")
         + "tee /etc/apt/sources.list.d/docker.list > /dev/null"],
        SUDO + ["apt-get", "update", "-y"],
        SUDO + ["apt-get", "install", "-y", "docker-ce", "docker-ce-cli",
                "containerd.io", "docker-buildx-plugin", "docker-compose-plugin"],
        SUDO + ["systemctl", "enable", "--now", "docker"],
    ]


def _nvidia_toolkit_steps() -> list[list[str]]:
    return [
        ["bash", "-c",
         "curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | "
         + ("" if IS_ROOT else "sudo ")
         + "gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg --yes"],
        ["bash", "-c",
         "curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | "
         "sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | "
         + ("" if IS_ROOT else "sudo ")
         + "tee /etc/apt/sources.list.d/nvidia-container-toolkit.list > /dev/null"],
        SUDO + ["apt-get", "update", "-y"],
        SUDO + ["apt-get", "install", "-y", "nvidia-container-toolkit"],
        SUDO + ["nvidia-ctk", "runtime", "configure", "--runtime=docker"],
        SUDO + ["systemctl", "restart", "docker"],
    ]


def build_dependencies() -> list[Dependency]:
    apt = lambda *p: SUDO + ["apt-get", "install", "-y", *p]
    return [
        Dependency("curl", "curl", ["curl", "--version"], [SUDO + ["apt-get", "update", "-y"], apt("curl")]),
        Dependency("git", "git", ["git", "--version"], [apt("git")]),
        Dependency("openssl", "OpenSSL", ["openssl", "version"], [apt("openssl")]),
        Dependency("ca", "ca-certificates", ["test", "-e", "/etc/ssl/certs/ca-certificates.crt"], [apt("ca-certificates")]),
        Dependency("gnupg", "gnupg", ["bash", "-c", "command -v gpg"], [apt("gnupg")]),
        Dependency("docker", "Docker Engine", ["docker", "--version"], _docker_repo_steps(),
                   note="Container runtime — the core of SATYAMEBA."),
        Dependency("compose", "Docker Compose v2", ["docker", "compose", "version"],
                   [apt("docker-compose-plugin")], note="Bundled with Docker CE."),
        Dependency("nvsmi", "NVIDIA driver", ["nvidia-smi"],
                   [apt("nvidia-driver")], required=False,
                   note="GPU driver. For the very new RTX 5070 you may need a 555+ "
                        "driver from NVIDIA's CUDA repo rather than Debian stable; a "
                        "reboot is required after install."),
        Dependency("nvtoolkit", "NVIDIA Container Toolkit",
                   ["bash", "-c", "command -v nvidia-ctk"], _nvidia_toolkit_steps(),
                   required=False, note="Lets containers use the GPU."),
    ]


# --------------------------------------------------------------------------- #
# GUI
# --------------------------------------------------------------------------- #
class SetupApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("SATYAMEBA · Setup Wizard")
        self.geometry("860x680")
        self.configure(bg="#0e1116")
        self.deps = build_dependencies()
        self.rows: dict[str, dict] = {}
        self.q: queue.Queue = queue.Queue()
        self._build_style()
        self._build_ui()
        self.after(100, self._drain_queue)

    # ---- styling ----
    def _build_style(self) -> None:
        s = ttk.Style(self)
        try:
            s.theme_use("clam")
        except tk.TclError:
            pass
        s.configure("TFrame", background="#0e1116")
        s.configure("TLabel", background="#0e1116", foreground="#e6edf3")
        s.configure("Header.TLabel", font=("Helvetica", 16, "bold"), foreground="#f5a623")
        s.configure("TButton", padding=6)
        s.configure("Horizontal.TProgressbar", troughcolor="#1c232d", background="#3fb950")

    # ---- layout ----
    def _build_ui(self) -> None:
        top = ttk.Frame(self); top.pack(fill="x", padx=16, pady=(14, 6))
        ttk.Label(top, text="◆ SATYAMEBA Setup", style="Header.TLabel").pack(side="left")
        ttk.Label(top, text=f"  running as {'root' if IS_ROOT else 'non-root (will use sudo)'}").pack(side="left")

        # Dependency table
        table = ttk.Frame(self); table.pack(fill="x", padx=16, pady=6)
        ttk.Label(table, text="Dependency", width=28, font=("Helvetica", 10, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(table, text="Status", width=14, font=("Helvetica", 10, "bold")).grid(row=0, column=1, sticky="w")
        ttk.Label(table, text="Notes", font=("Helvetica", 10, "bold")).grid(row=0, column=2, sticky="w")
        for i, d in enumerate(self.deps, start=1):
            ttk.Label(table, text=d.name + ("" if d.required else "  (optional)")).grid(row=i, column=0, sticky="w", pady=2)
            st = ttk.Label(table, text="—", width=14); st.grid(row=i, column=1, sticky="w")
            ttk.Label(table, text=d.note, wraplength=420, foreground="#8b949e").grid(row=i, column=2, sticky="w")
            self.rows[d.key] = {"status": st}

        # Progress + actions
        prog = ttk.Frame(self); prog.pack(fill="x", padx=16, pady=8)
        self.pbar = ttk.Progressbar(prog, mode="determinate", maximum=100)
        self.pbar.pack(fill="x")
        self.statusvar = tk.StringVar(value="Idle. Click ‘Check dependencies’.")
        ttk.Label(prog, textvariable=self.statusvar, foreground="#8b949e").pack(anchor="w", pady=(4, 0))

        btns = ttk.Frame(self); btns.pack(fill="x", padx=16)
        self.btn_check = ttk.Button(btns, text="1 · Check dependencies", command=self._run_checks)
        self.btn_check.pack(side="left", padx=4)
        self.btn_fix = ttk.Button(btns, text="2 · Install / fix missing", command=self._run_installs)
        self.btn_fix.pack(side="left", padx=4)
        self.btn_gpu = ttk.Button(btns, text="3 · Verify GPU passthrough", command=self._verify_gpu)
        self.btn_gpu.pack(side="left", padx=4)
        self.btn_docker_group = ttk.Button(btns, text="Add me to docker group", command=self._add_docker_group)
        self.btn_docker_group.pack(side="left", padx=4)
        self.btn_scan = ttk.Button(btns, text="Scan storage & resources", command=self._scan_resources)
        self.btn_scan.pack(side="left", padx=4)
        self.btn_public = ttk.Button(btns, text="🌐 Expose on a domain (Cloudflare)", command=self._public_domain)
        self.btn_public.pack(side="left", padx=4)

        # Role / bootstrap
        role = ttk.LabelFrame(self, text=" Bootstrap this node ")
        role.pack(fill="x", padx=16, pady=10)
        self.rolevar = tk.StringVar(value="master")
        ttk.Radiobutton(role, text="Master", variable=self.rolevar, value="master", command=self._toggle_role).grid(row=0, column=0, sticky="w", padx=6, pady=4)
        ttk.Radiobutton(role, text="Worker", variable=self.rolevar, value="worker", command=self._toggle_role).grid(row=0, column=1, sticky="w")
        self.gpuvar = tk.BooleanVar(value=False)
        ttk.Checkbutton(role, text="This node has a GPU", variable=self.gpuvar).grid(row=0, column=2, sticky="w", padx=6)
        self.singlevar = tk.BooleanVar(value=False)
        ttk.Checkbutton(role, text="Single-host (compose)", variable=self.singlevar).grid(row=0, column=3, sticky="w")
        self.nfsvar = tk.BooleanVar(value=False)
        ttk.Checkbutton(role, text="Shared NFS storage (work follows users)",
                        variable=self.nfsvar).grid(row=3, column=2, columnspan=2, sticky="w", padx=6)

        self.fields: dict[str, tk.Entry] = {}
        self._add_field(role, "domain", "Domain", "satyameba.local", 1, 0)
        self._add_field(role, "advertise", "Master/advertise IP", "", 1, 2)
        self._add_field(role, "join", "Swarm join-token (worker)", "", 2, 0)
        self._add_field(role, "secret", "Node secret (worker)", "", 2, 2)
        self._add_field(role, "users", "Plan for N users", "8", 3, 0)
        self.btn_boot = ttk.Button(role, text="Bootstrap node ▶", command=self._bootstrap)
        self.btn_boot.grid(row=4, column=0, columnspan=4, pady=8)

        # Log
        logf = ttk.Frame(self); logf.pack(fill="both", expand=True, padx=16, pady=(0, 12))
        self.log = tk.Text(logf, height=12, bg="#0a0d12", fg="#c9d1d9", insertbackground="#fff", relief="flat")
        self.log.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(logf, command=self.log.yview); sb.pack(side="right", fill="y")
        self.log.config(yscrollcommand=sb.set)
        self._toggle_role()

    def _add_field(self, parent, key, label, default, r, c) -> None:
        ttk.Label(parent, text=label).grid(row=r, column=c, sticky="w", padx=6)
        e = ttk.Entry(parent, width=28); e.insert(0, default)
        e.grid(row=r, column=c + 1, sticky="w", padx=6, pady=2)
        self.fields[key] = e

    # ---- helpers ----
    def _toggle_role(self) -> None:
        worker = self.rolevar.get() == "worker"
        for k in ("join", "secret"):
            self.fields[k].config(state="normal" if worker else "disabled")

    def _logln(self, text: str) -> None:
        self.q.put(("log", text))

    def _set_status(self, key: str, status: str) -> None:
        self.q.put(("status", (key, status)))

    def _drain_queue(self) -> None:
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "log":
                    self.log.insert("end", payload + "\n"); self.log.see("end")
                elif kind == "status":
                    key, status = payload
                    colors = {"ok": "#3fb950", "missing": "#d29922", "error": "#f85149", "checking": "#4c8dff"}
                    label = {"ok": "✔ present", "missing": "✗ missing", "error": "error", "checking": "…"}.get(status, status)
                    self.rows[key]["status"].config(text=label, foreground=colors.get(status, "#e6edf3"))
                elif kind == "progress":
                    self.pbar["value"] = payload
                elif kind == "statusbar":
                    self.statusvar.set(payload)
                elif kind == "enable":
                    for b in (self.btn_check, self.btn_fix, self.btn_gpu, self.btn_boot,
                              self.btn_docker_group, self.btn_scan, self.btn_public):
                        b.config(state="normal")
        except queue.Empty:
            pass
        self.after(100, self._drain_queue)

    def _disable_buttons(self) -> None:
        for b in (self.btn_check, self.btn_fix, self.btn_gpu, self.btn_boot,
                  self.btn_docker_group, self.btn_scan, self.btn_public):
            b.config(state="disabled")

    def _run(self, cmd: list[str]) -> int:
        self._logln("  $ " + " ".join(cmd))
        try:
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        except FileNotFoundError as e:
            self._logln(f"  ! {e}")
            return 127
        for line in p.stdout:  # type: ignore
            self._logln("    " + line.rstrip())
        return p.wait()

    # ---- actions (each runs on a thread) ----
    def _thread(self, target) -> None:
        self._disable_buttons()
        threading.Thread(target=self._wrap(target), daemon=True).start()

    def _wrap(self, target):
        def inner():
            try:
                target()
            except Exception as e:  # never let a thread die silently
                self._logln(f"  ! unexpected error: {e}")
            finally:
                self.q.put(("enable", None))
        return inner

    def _public_domain(self) -> None:
        token = simpledialog.askstring(
            "Expose on a domain — Cloudflare Tunnel",
            "Paste your Cloudflare Tunnel TOKEN\n"
            "(Cloudflare Zero Trust → Networks → Tunnels → create a tunnel →\n"
            "'Install connector' shows a token). Leave blank to cancel.",
            show="*", parent=self)
        if not token or not token.strip():
            self._logln("  (Cloudflare setup cancelled — no token)")
            return
        host = simpledialog.askstring(
            "Public hostname (optional)",
            "Public hostname for the site, e.g. notebooks.yourdomain.com\n"
            "(optional — you can also set it in the Cloudflare dashboard).",
            parent=self) or ""
        self._pd_token = token.strip()
        self._pd_host = host.strip()
        self._thread(self._do_public_domain)

    def _do_public_domain(self) -> None:
        self.q.put(("statusbar", "Setting up Cloudflare Tunnel…"))
        cmd = SUDO + ["bash", str(REPO_ROOT / "setup" / "public_domain.sh"),
                      "--token", self._pd_token, "--harden"]
        if self._pd_host:
            cmd += ["--hostname", self._pd_host]
        rc = self._run(cmd)
        if rc == 0:
            self._logln("  ✔ Cloudflare Tunnel installed as a boot service.")
            self._logln("  → In the Cloudflare dashboard set the hostname → service")
            self._logln("    https://localhost:443  with 'No TLS Verify' = ON.")
        else:
            self._logln(f"  ! public_domain.sh exited with code {rc} (see log above).")
        self.q.put(("statusbar", "Cloudflare Tunnel step finished."))

    def _run_checks(self) -> None:
        self._thread(self._do_checks)

    def _do_checks(self) -> None:
        self.q.put(("statusbar", "Checking dependencies…"))
        n = len(self.deps)
        for i, d in enumerate(self.deps):
            self._set_status(d.key, "checking")
            ok = shutil.which(d.check[0]) is not None or d.check[0] in ("test", "bash")
            rc = self._run(d.check) if ok else 1
            d.status = "ok" if rc == 0 else "missing"
            self._set_status(d.key, d.status)
            self.q.put(("progress", int((i + 1) / n * 100)))
        missing = [d.name for d in self.deps if d.status != "ok" and d.required]
        self.q.put(("statusbar", "All required dependencies present." if not missing
                    else f"Missing required: {', '.join(missing)} — click ‘Install / fix’."))

    def _run_installs(self) -> None:
        self._thread(self._do_installs)

    def _do_installs(self) -> None:
        targets = [d for d in self.deps if d.status == "missing" and d.install]
        if not targets:
            self.q.put(("statusbar", "Nothing to install — run a check first."))
            return
        self.q.put(("statusbar", "Installing missing dependencies…"))
        for i, d in enumerate(targets):
            self._logln(f"\n=== Installing {d.name} ===")
            failed = False
            for step in d.install:
                if self._run(step) != 0:
                    failed = True
                    self._logln(f"  ! step failed for {d.name}")
                    break
            rc = self._run(d.check)
            d.status = "ok" if rc == 0 else ("error" if failed else "missing")
            self._set_status(d.key, d.status)
            self.q.put(("progress", int((i + 1) / len(targets) * 100)))
        self.q.put(("statusbar", "Install pass complete. Re-check to confirm."))

    def _verify_gpu(self) -> None:
        self._thread(self._do_verify_gpu)

    def _do_verify_gpu(self) -> None:
        self.q.put(("statusbar", "Verifying GPU passthrough into a container…"))
        if shutil.which("nvidia-smi") is None:
            self._logln("  ! No NVIDIA driver detected on host — skipping.")
            self.q.put(("statusbar", "No GPU driver; skipped."))
            return
        rc = self._run(["docker", "run", "--rm", "--gpus", "all",
                        "nvidia/cuda:12.4.1-base-ubuntu22.04", "nvidia-smi"])
        if rc == 0:
            self._logln("  ✔ GPU is visible inside containers.")
            self.q.put(("statusbar", "GPU passthrough OK."))
        else:
            self._logln("  ! GPU not visible in container. Ensure the NVIDIA "
                        "Container Toolkit is installed and docker was restarted.")
            self.q.put(("statusbar", "GPU passthrough FAILED — see log."))

    def _add_docker_group(self) -> None:
        user = os.environ.get("SUDO_USER") or os.environ.get("USER") or ""
        if not user or user == "root":
            messagebox.showinfo("docker group", "Run the wizard via sudo from your normal user.")
            return
        self._thread(lambda: self._do_add_group(user))

    def _do_add_group(self, user: str) -> None:
        self._run(SUDO + ["groupadd", "-f", "docker"])
        self._run(SUDO + ["usermod", "-aG", "docker", user])
        self._logln(f"  ✔ Added {user} to the docker group. Log out/in to take effect.")
        self.q.put(("statusbar", f"{user} added to docker group (re-login needed)."))

    def _scan_resources(self) -> None:
        self._thread(self._do_scan_resources)

    def _do_scan_resources(self) -> None:
        self.q.put(("statusbar", "Scanning storage / RAM / CPU…"))
        # Ensure a .env exists so the scan can write into it.
        if not (REPO_ROOT / ".env").exists():
            self._run(["bash", str(REPO_ROOT / "scripts" / "gen_secrets.sh")])
        users = self.fields.get("users")
        n = (users.get().strip() if users else "") or "8"
        self._logln("\n=== Storage & resource scan ===")
        rc = self._run(["bash", str(REPO_ROOT / "scripts" / "scan_resources.sh"), "--users", n])
        self.q.put(("statusbar", "Scan complete — allocations written to .env."
                    if rc == 0 else "Scan failed — see log."))

    def _bootstrap(self) -> None:
        self._thread(self._do_bootstrap)

    def _do_bootstrap(self) -> None:
        role = self.rolevar.get()
        gpu = self.gpuvar.get()
        domain = self.fields["domain"].get().strip() or "satyameba.local"
        adv = self.fields["advertise"].get().strip()
        if role == "master":
            users = (self.fields["users"].get().strip() or "8")
            cmd = ["bash", str(REPO_ROOT / "setup" / "master_init.sh"),
                   "--domain", domain, "--users", users]
            if self.singlevar.get():
                cmd.append("--single")
            if adv:
                cmd += ["--advertise-addr", adv]
            if gpu:
                cmd.append("--gpu")
            if self.nfsvar.get():
                cmd.append("--nfs")
        else:
            join = self.fields["join"].get().strip()
            secret = self.fields["secret"].get().strip()
            if not (adv and join and secret):
                messagebox.showwarning("Worker", "Master IP, join-token and node secret are required.")
                return
            cmd = ["bash", str(REPO_ROOT / "setup" / "worker_join.sh"),
                   "--master-ip", adv, "--join-token", join, "--node-secret", secret,
                   "--gateway", f"https://{adv}"]
            if gpu:
                cmd.append("--gpu")
            if self.nfsvar.get():
                cmd += ["--nfs-server", adv]
        self.q.put(("statusbar", f"Bootstrapping {role}…"))
        rc = self._run(cmd)
        self.q.put(("statusbar", f"Bootstrap {'succeeded' if rc == 0 else 'failed — see log'}."))


def main() -> None:
    if not IS_ROOT:
        print("Note: not running as root — install steps will call sudo and may prompt.")
    app = SetupApp()
    app.mainloop()


if __name__ == "__main__":
    main()
