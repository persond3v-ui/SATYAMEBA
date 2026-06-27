<div align="center">

# ◆ SATYAMEBA

**Your own private, multi-node Jupyter cloud — a Google-Colab-style notebook
platform that runs on your lab's own desktops.**

Register → admin approves → log in → launch an **isolated** GPU notebook that the
cluster schedules onto a free machine. Full admin control, live CPU/GPU/network/
storage dashboards, and OWASP-aware hardening — all dockerized and plug-n-play.

*Owner & author: **Samaraho Mukherjee** · © 2026 · see [`OWNERSHIP.md`](OWNERSHIP.md)*

</div>

---

## What you get

- 🧑‍💻 **Colab-like workspace** — users import or create Jupyter notebooks and run
  them on real lab hardware (i7 + RTX 5070 nodes).
- 🛂 **Approval-gated onboarding** — anyone can register, but an **admin must
  approve** before they can log in. Admins can suspend/“kick off” users instantly.
- 📦 **Isolated execution** — every notebook runs in its own hardened container
  (`cap_drop=ALL`, no host mounts, CPU/mem caps, optional GPU).
- ⚖️ **Cluster load balancing** — Docker Swarm schedules notebooks onto whichever
  node has capacity / a free GPU.
- 📊 **Live monitoring** — Prometheus + Grafana show per-node CPU, GPU, network
  and storage, embedded right in the admin dashboard.
- 🔐 **Security-first** — TLS-only edge (just ports 80/443), RS256 JWTs, per-request
  HMAC signing, ORM-only DB access, rate limiting, bot filtering, a tamper-evident
  audit log, and an OWASP Top-10 mapping ([`docs/SECURITY.md`](docs/SECURITY.md)).
- 🖱️ **tkinter setup wizard** — checks & installs every dependency (Docker, NVIDIA
  toolkit…) with progress bars, verifies GPU passthrough, and bootstraps the node.
- ✍️ **Cryptographically signed ownership** — `SHA256SUMS` + detached GPG signature.

> **Honesty note:** a few requested ideas can't be real security and aren't sold as
> such — client-side JS obfuscation only slows casual snooping, and no token scheme
> can stop a user from proxying *their own* browser session through Burp. Those are
> handled correctly (server-side authz, short-lived signed/rotated tokens, replay
> protection) and explained plainly in [`docs/SECURITY.md`](docs/SECURITY.md).

---

## Architecture at a glance

```
clients ──https(80/443)──▶ edge(nginx, TLS, SPA, proxy)
                              ├─▶ gateway (FastAPI + SQLAlchemy)  ──▶ postgres
                              ├─▶ jupyterhub  ──spawns──▶ isolated notebook containers
                              ├─▶ grafana  ◀── prometheus ◀── node-exporter / cAdvisor / DCGM
                              └─ (everything internal; only the edge is published)

MASTER (swarm manager) ──:2377──▶ WORKER 1 · WORKER 2 · WORKER 3 …  (same VLAN)
```

Full diagram and rationale: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

---

## Quick start (one machine, ~5 minutes)

```bash
git clone <this-repo> SATYAMEBA && cd SATYAMEBA

# GUI wizard: Check → Install/fix → Verify GPU → role "Master" + "Single-host"
sudo apt-get install -y python3-tk
sudo python3 setup/satyameba_setup.py
```

…or fully headless:

```bash
./setup/master_init.sh --single --gpu        # builds, generates secrets, starts
```

Open **https://localhost/**. Your admin username/password are printed by the
wizard and saved in `.env` (`SAT_BOOTSTRAP_ADMIN_*`). Change the password on first
login.

Try it: register a second account in an incognito window → approve it from
**Admin → Approvals** → log in as that user → **Launch notebook**.

---

## The 4-desktop lab (multi-node)

On the **master**:

```bash
./setup/master_init.sh --advertise-addr 192.168.1.10 --domain satyameba.local
```

It initialises the swarm, deploys the stack, and prints a copy-paste command for
workers. On **each worker** (same VLAN):

```bash
sudo ./setup/worker_join.sh \
    --master-ip 192.168.1.10 --join-token SWMTKN-1-xxxx \
    --node-secret <printed-secret> --gateway https://192.168.1.10 \
    --gpu --master-ssh user@192.168.1.10
```

The worker joins the swarm, builds the notebook image, registers itself (shows up
under **Admin → Nodes**), and starts a heartbeat. Done. Add as many nodes as you
like — repeat the one command. Details: [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).

---

## Using the wizard

| Button | What it does |
|--------|--------------|
| **1 · Check dependencies** | Probes Docker, Compose v2, NVIDIA driver + Container Toolkit, openssl, curl, git… with a progress bar and per-item status. |
| **2 · Install / fix missing** | Installs/repairs anything missing via the official Docker & NVIDIA apt repos. |
| **3 · Verify GPU passthrough** | Runs `docker run --gpus all … nvidia-smi` to prove containers see the GPU. |
| **Add me to docker group** | `usermod -aG docker $USER` so you can run docker without sudo. |
| **Bootstrap node ▶** | Runs the master or worker bootstrap with the fields you filled in. |

---

## Admin dashboard

- **Overview** — pending/approved/suspended counts, node count, audit-chain integrity.
- **Approvals** — approve (as user or admin) or reject join requests.
- **Users** — see everyone, their status & last login; **kick off** (suspend) or reinstate.
- **Nodes** — every machine in the cluster, role, GPU, online status, last heartbeat.
- **Sessions** — which users have a notebook running right now.
- **Monitoring** — embedded Grafana: CPU / GPU / network / storage per node.
- **Audit** — full, tamper-evident log of every privileged action.

---

## Repository layout

```
SATYAMEBA/
├── gateway/           FastAPI auth & orchestration API (ORM models, JWT, signing, audit)
├── frontend/          Vanilla-JS SPA + the nginx edge (TLS, reverse proxy)
├── jupyterhub/        Hub config, gateway-backed authenticator, hardened notebook image
├── monitoring/        Prometheus (compose + swarm) + Grafana provisioning & dashboard
├── setup/             tkinter wizard, master_init.sh, worker_join.sh
├── scripts/           gen_secrets.sh, sign_release.sh, verify_release.sh
├── docs/              ARCHITECTURE.md · SECURITY.md · DEPLOYMENT.md
├── docker-compose.yml         single-host stack
├── docker-compose.swarm.yml   multi-node Swarm stack
├── OWNERSHIP.md · LICENSE · SHA256SUMS   ownership & integrity
└── Makefile           make help
```

## Handy commands

```bash
make help          # list everything
make scan USERS=16 # size .env to this host's storage/RAM/CPU for N users
make up            # build images (incl. notebook) + start single-host stack
make logs          # tail logs
make obfuscate     # build edge with obfuscated client JS
make sign KEY="Samaraho Mukherjee <you@example.com>" TAG=v0.1.0   # sign release
make verify        # verify integrity + ownership signature
```

## Security & ownership

- Threat model and OWASP Top-10 mapping: [`docs/SECURITY.md`](docs/SECURITY.md).
- This project is owned by **Samaraho Mukherjee**. Verify provenance:
  ```bash
  ./scripts/verify_release.sh && gpg --verify SHA256SUMS.asc SHA256SUMS
  ```

## Characteristics, limits & status

- **[`docs/CHARACTERISTICS.md`](docs/CHARACTERISTICS.md)** — capabilities,
  resource profiles, storage behaviour, ports, scaling, HA limits, and every
  default you need to know.
- **[`docs/KNOWN_ISSUES.md`](docs/KNOWN_ISSUES.md)** — self-audited flaw log with
  status (most now fixed: SSO, profiles, shared datasets, live Prometheus metrics,
  Redis-shared limits, GPU swarm runtime, tests/CI…).

Headline features now in: one-click **SSO** into JupyterLab, **resource profiles**
(Small/Medium/Large/GPU), a **shared dataset volume**, **no upload cap**,
**storage-aware sizing** (`make scan`), live cluster metrics pulled straight from
Prometheus into the admin Overview, and a committed **test suite + CI**.

Security extras now in: **TOTP 2FA** (optionally mandatory for admins), forced
rotation of the seeded admin password, an optional **gVisor** sandbox runtime,
and a strict **CSP** on the SPA.

## Remaining hardening (needs your infra/hardware)

- Replicated Postgres for full HA (you supply it; the wiring is in place).
- OIDC/LDAP institutional login (needs your identity provider).
- Hard per-user disk quotas (enable XFS prjquota).
- Verify GPU passthrough and gVisor on real RTX 5070 hardware.

---

<div align="center"><sub>SATYAMEBA · built for labs that want Colab on their own metal · © 2026 Samaraho Mukherjee</sub></div>
