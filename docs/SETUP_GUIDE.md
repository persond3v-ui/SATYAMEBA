# SATYAMEBA — Complete Setup Guide (Master + Workers, every feature live)

This is the end-to-end runbook for standing up the whole lab: the master
(control plane) and every worker desktop, with GPU scheduling, shared storage,
at-rest encryption, the owner break-glass, public HTTPS, auto-start on boot, and
the console dashboard. Every command and `.env` field here is real and matches
the scripts in this repo.

> **TL;DR for the impatient:** on the master, run
> `sudo ./setup/cluster_setup.sh`, answer the prompts (it will SSH into every
> worker and do the rest), open `https://satyameba.local/`, log in with the
> admin password printed into `.env`, change it. Done. The sections below explain
> what each step does so you can also do it by hand and so nothing surprises you.

---

## 0. Before you start (do this once per machine)

**Network**
- Put all 4 desktops on the same VLAN/switch. Pick a stable IP for the master
  (e.g. `192.168.1.10`). The workers reach the master on that IP.
- Only ports **80** and **443** are ever exposed to users. Swarm uses 2377/7946/4789
  *between nodes on the VLAN only* — do not forward those to the internet.
- Optional but recommended: add `satyameba.local` → master IP in each machine's
  `/etc/hosts` (or your LAN DNS), so the domain resolves.

**OS prerequisites**
- Debian (or any systemd distro). You need `git`, `curl`, `openssl`. The wizards
  install Docker and the NVIDIA toolkit for you if missing.
- A user that can `sudo` (or root). The cluster wizard escalates itself.

**Get the code on the master**
```bash
git clone <your-repo-url> ~/SATYAMEBA      # or copy the folder
cd ~/SATYAMEBA
git checkout claude/jupyter-saas-platform-vr13lj
```
You only need the code on the **master**. The cluster wizard rsyncs it to the
workers. (For the manual path you copy it yourself — see §3.)

---

## 1. The three ways to install (pick one)

| Path | Command | When to use |
|------|---------|-------------|
| **A — One-button cluster** | `sudo ./setup/cluster_setup.sh` | The real lab: master + all workers in one shot. **Recommended.** |
| **B — Manual master + workers** | `./setup/master_init.sh …` then `./setup/worker_join.sh …` on each node | You want to see/control each step, or SSH-from-master isn't available. |
| **C — Single host (demo)** | `./setup/master_init.sh --single` | Everything on one machine, no swarm. Great for trying it out. |

There is also a **graphical wizard** (`python3 setup/satyameba_setup.py`) and a
**TUI one-button wizard** (`./setup/wizard.sh`) that wrap the same scripts with
buttons. Use them if you prefer clicking; the CLI below is the source of truth.

---

## 2. Path A — the one-button cluster wizard (recommended)

Run **on the master**:
```bash
sudo ./setup/cluster_setup.sh
```
It re-execs itself as root, then asks you a short list of questions. Here is
**exactly what each prompt does**:

| Prompt | Default | What it controls |
|--------|---------|------------------|
| **Master IP** | first NIC IP | The address workers use to reach the master (`--advertise-addr`). Must be the VLAN IP. |
| **Dashboard domain** | `satyameba.local` | Goes into the TLS cert SANs and CORS allow-list. Users browse here. |
| **Expected number of users** | 16 | Sizes per-user RAM/CPU/storage (see `scan_resources.sh`) and the welcome capacity. |
| **Owner username** | `samaraho` | The **un-removable owner** account created on every node (break-glass). |
| **Owner email** | `owner@satyameba.local` | Owner's contact / login email. |
| **NVIDIA GPUs to schedule?** | yes | Installs the NVIDIA Container Toolkit, labels GPU nodes, builds the CUDA notebook image. |
| **Share storage via NFS?** | yes | Master exports `/srv/satyameba/users`; workers mount it so a user's files follow them to any node. |
| **Encrypt user data at rest?** | yes | Turns on gocryptfs per-user encryption (`SAT_USER_ENCRYPTION=gocryptfs`). |
| **SSH username for the other nodes** | `root` | How the wizard logs into workers. Use `root` if root SSH is allowed, else a sudo user. |
| **Worker node IPs** | (blank) | Space-separated list, e.g. `192.168.1.11 192.168.1.12 192.168.1.13`. Blank = single host. |
| **Root/SSH password** | — | Typed once, hidden. Used (via `sshpass -e`, never shown in `ps`) to act as root on every node. |

**What it then does, verifying each step (nothing proceeds on a silent failure):**
1. Checks SSH+sudo reachability on **every** worker *before* changing anything.
2. **GPU cross-check:** reads each node's NVIDIA driver and picks **one** CUDA/torch
   wheel that works on the *oldest* driver in the cluster — so a node that **isn't**
   an RTX 5070 still integrates. (`driver_to_torch`: ≥555→cu124, ≥535→cu121, ≥520→cu118.)
3. Installs Docker + NVIDIA toolkit where missing.
4. Brings up the **master** (secrets, images, swarm init, stack on 80/443) via
   `master_init.sh`.
5. Enables **at-rest encryption** and the **owner break-glass** on the master.
6. For each worker: rsyncs the code to `/opt/satyameba`, joins the swarm, builds
   the notebook image, registers with the gateway, sets up encryption + owner,
   and GPU-labels the node on the manager.
7. Verifies the site answers on `https://<master>/healthz`, prints `docker node ls`
   and a GPU check.

Everything is logged to `/var/log/satyameba-cluster.<ts>.log`. **Idempotent** — safe
to re-run if a node hiccups.

When it finishes you'll see the dashboard URL and a note that admin/owner
credentials are in `.env`. **Skip to §8 (first login) and §11 (verify).**

---

## 3. Path B — manual master, then manual workers

### 3a. Bring up the master
```bash
cd ~/SATYAMEBA
sudo ./setup/master_init.sh \
     --advertise-addr 192.168.1.10 \
     --domain satyameba.local \
     --users 16 \
     --gpu \
     --nfs
```
Flags:
- `--advertise-addr IP` — VLAN IP workers connect to (auto-detected if omitted).
- `--domain D` — TLS/CORS domain (default `satyameba.local`).
- `--users N` — sizes per-user resources for N users.
- `--gpu` — this master also has a GPU to schedule on (labels it, builds CUDA image).
- `--nfs` — export shared user storage from this master (sets storage mode to `host`).
- `--single` — single-host compose instead of swarm (Path C).

`master_init.sh` runs `gen_secrets.sh` (writes `.env`, RSA JWT keypair, TLS cert),
scans resources, configures GPU runtime, builds the four images
(`gateway`, `jupyterhub`, `edge`, `notebook`), inits the swarm, labels GPU, and
`docker stack deploy`s. **At the end it prints the exact worker command**, including
the live join token and node secret. Copy that.

### 3b. Join each worker
The master prints something like:
```bash
sudo ./setup/worker_join.sh \
     --master-ip 192.168.1.10 \
     --join-token SWMTKN-1-xxxxx \
     --node-secret <SAT_INTERNAL_SHARED_SECRET> \
     --gateway https://192.168.1.10 \
     --nfs-server 192.168.1.10 \
     --gpu --master-ssh user@192.168.1.10
```
Copy the project to the worker first (`rsync -az --exclude .git ~/SATYAMEBA/ worker:/opt/satyameba/`),
then run the above **on the worker**. What it does:
1. Joins the swarm (`:2377`).
2. Configures the GPU runtime (if `--gpu`) so the node advertises its GPUs.
3. Mounts the NFS share (if `--nfs-server`).
4. Builds the notebook image locally (with the right CUDA wheel via `SAT_TORCH_INDEX`).
5. Registers with the gateway (appears in **Admin → Nodes**), using a node token =
   `HMAC(node_secret, hostname)`.
6. Installs a **heartbeat timer** (every 30s) so the dashboard shows it online.
7. GPU-labels the node — automatically if you passed `--master-ssh`, otherwise it
   prints the one command to run on the master:
   `docker node update --label-add satyameba.gpu=true <NODE_ID>`.

Repeat 3b for each of the other 3 desktops.

---

## 4. Path C — single host (demo)
```bash
./setup/master_init.sh --single --gpu --domain satyameba.local
```
Brings the whole stack up with `docker compose up -d` on one machine. No swarm,
no workers. Open `https://satyameba.local/`.

---

## 5. Every `.env` field, explained

`.env` is generated by `gen_secrets.sh` with strong random secrets and
`chmod 600`. **Never `source` it by hand** — use `scripts/load_env.sh`'s
`load_env` (the scripts already do). To change a value safely, use
`scripts/set_env.sh KEY value` or re-run `gen_secrets.sh --force` (regenerates
secrets — only on a fresh install).

**Identity & project**
| Field | Meaning |
|-------|---------|
| `SAT_ENVIRONMENT` | `production` (locked down: API docs off, fails closed on weak secrets) or `development`. |
| `SAT_PROJECT_NAME` | Display name. |
| `SAT_OWNER` | Owner name baked into the cert/branding. **Quoted** because it has a space. |

**Database**
| Field | Meaning |
|-------|---------|
| `POSTGRES_USER/PASSWORD/DB` | Postgres credentials (random pw). |
| `SAT_DATABASE_URL` | SQLAlchemy URL the gateway uses. Point this at the HA/PgBouncer overlay if you use one. |

**Auth & signing**
| Field | Meaning |
|-------|---------|
| `SAT_JWT_ALGORITHM` | `RS256` (asymmetric). |
| `SAT_JWT_PRIVATE/PUBLIC_KEY_PATH` | Where the RSA keypair is mounted (docker secret). |
| `SAT_ACCESS_TOKEN_TTL_SECONDS` | Access-token lifetime (900s = 15min). |
| `SAT_REFRESH_TOKEN_TTL_SECONDS` | Refresh-token lifetime (7 days). |
| `SAT_REQUEST_SIGNING_ENABLED` | Per-request HMAC signing on internal calls. |
| `SAT_REQUEST_SIGNING_SKEW_SECONDS` | Allowed clock skew for signatures (120s). |

**Bootstrap admin** (created on first boot — **change the password after login**)
| Field | Meaning |
|-------|---------|
| `SAT_BOOTSTRAP_ADMIN_EMAIL/USERNAME/PASSWORD` | The first admin account. |

**JupyterHub / internal**
| Field | Meaning |
|-------|---------|
| `SAT_HUB_API_URL` / `SAT_HUB_API_TOKEN` | Gateway ↔ Hub API. |
| `SAT_HUB_PUBLIC_URL` | Public path the Hub is served under (`/hub`). |
| `SAT_INTERNAL_SHARED_SECRET` | The cluster secret. Workers derive their node token from it. Keep it secret. |
| `SAT_DATA_ENCRYPTION_KEY` | Fernet key for at-rest TOTP/2FA secrets (independent of the internal secret). |
| `SAT_SSO_TOKEN_TTL_SECONDS` | Single-use SSO handoff token lifetime (60s). |
| `SAT_PROMETHEUS_URL` / `SAT_REDIS_URL` | Metrics + cache endpoints. |

**Spawner / notebooks**
| Field | Meaning |
|-------|---------|
| `SAT_SPAWNER` | `docker` (compose) or swarm spawner. |
| `SAT_NOTEBOOK_IMAGE` | The per-user image (`satyameba/notebook:latest`). |
| `SAT_NETWORK` | Overlay network name. |
| `SAT_GPU_ENABLED` | Whether GPUs are scheduled (flipped to `true` by `--gpu`). |
| `SAT_GPU_RESOURCE` | Swarm generic-resource name for GPUs (`gpu`). |
| `SAT_MEM_LIMIT` / `SAT_CPU_LIMIT` | Default per-notebook RAM/CPU cap (`4G` / `2`). |

**Storage**
| Field | Meaning |
|-------|---------|
| `SAT_SHARED_VOLUME` / `SAT_SHARED_MODE` | The class-wide shared folder + rw/ro. |
| `SAT_USER_STORAGE_MODE` | `volume` (per-node docker volume) or `host` (NFS-backed, set by `--nfs`). |
| `SAT_USER_HOST_BASE` / `SAT_SHARED_HOST_PATH` | Host paths for `host` mode. |
| `SAT_USER_STORAGE_LIMIT_GB` | Per-user quota (20 GB). |
| `SAT_STORAGE_QUOTA_ENFORCE` | Hard-enforce the quota (off by default). |
| `SAT_EXPECTED_USERS` / `SAT_FREE_STORAGE_GB` / `SAT_TOTAL_STORAGE_GB` | Capacity bookkeeping from the resource scan. |

**Security & limits**
| Field | Meaning |
|-------|---------|
| `SAT_CORS_ORIGINS` | Allowed browser origins. Add your public domain here when you expose it. |
| `SAT_RATE_LIMIT_PER_MINUTE` / `SAT_AUTH_RATE_LIMIT_PER_MINUTE` | API + login rate caps. |
| `SAT_BOT_FILTER_ENABLED` | Drops obvious bot/scanner traffic. |
| `SAT_REQUIRE_ADMIN_2FA` | Force TOTP 2FA for admins (turn **on** before public exposure). |
| `SAT_NODE_OFFLINE_SECONDS` | After this with no heartbeat, a node shows offline (90s). |
| `SAT_AUDIT_RETENTION_DAYS` | `0` = keep the tamper-evident audit log forever. |
| `SAT_MAX_UPLOAD` | Upload size cap (`0` = unlimited). |
| `SAT_SANDBOX_RUNTIME` | Container runtime for untrusted users; set to `runsc` (gVisor) via `setup_gvisor.sh`. |
| `GF_SECURITY_ADMIN_PASSWORD` | Grafana admin password. |

---

## 6. GPU scheduling — how it behaves once live

- Nodes with a GPU are labelled `satyameba.gpu=true`; GPU notebooks only land there.
- The **dynamic scheduler** (`gateway/.../scheduler.py`):
  - **Active users ≤ GPU count** → each gets an **exclusive whole GPU/node**.
  - **Active users > GPU count** → **concurrent sharing** (MPS / `NVIDIA_VISIBLE_DEVICES=all`).
  - Admins can grant a one-session **GPU boost** from the dashboard.
- The CUDA wheel is cross-checked across the cluster so mixed GPUs all work
  (oldest driver decides; an RTX 5070 and an older card coexist).
- Verify anytime: `./scripts/verify_gpu.sh`.

---

## 7. Optional features and how to turn each one on

| Feature | How to enable | Script |
|---------|---------------|--------|
| **Auto-start on boot** | `sudo ./setup/install_services.sh --mode swarm --tui` | systemd units: stack, cleanup timer, console TUI. |
| **Shared NFS storage** | `--nfs` on master_init / wizard prompt | `scripts/setup_nfs.sh`. Files follow users across nodes. |
| **At-rest encryption** | wizard prompt, or `setup/gocryptfs_setup.sh` + `set_env.sh SAT_USER_ENCRYPTION gocryptfs` | per-user gocryptfs. |
| **Owner break-glass** | `owner-setup/owner_setup.sh --role master …` | un-removable owner, invisible to audit/admin lists. See `owner-setup/README.md`. |
| **Public HTTPS on your domain** | `sudo ./setup/public_domain.sh --token <CF_TUNNEL_TOKEN> --harden` | Cloudflare Tunnel; `--harden` flips to production + admin 2FA + CORS. |
| **Quick public link (no domain)** | `sudo ./setup/ngrok_setup.sh` | ngrok tunnel for a demo. |
| **HA Postgres** | deploy `docker-compose.ha-db.yml` (+ `docker-compose.pgbouncer.yml`) | repmgr/pgpool + PgBouncer. |
| **gVisor sandbox for untrusted users** | `./scripts/setup_gvisor.sh` then set `SAT_SANDBOX_RUNTIME=runsc` | stronger isolation. |
| **Console dashboard (headless nodes)** | `--tui` flag above; remove desktop with `setup/uninstall_desktop.sh` (re-add with `reinstall_desktop.sh`) | `tui/satyameba_tui.py` on tty1. |
| **Periodic cleanup** | installed with services; or `./scripts/cleanup.sh` | reclaims disk every 6h. |
| **Real TLS cert** | `./scripts/issue_cert.sh` (Let's Encrypt) | replaces the self-signed cert. |
| **Manager HA (promote workers)** | `./scripts/promote_managers.sh` | quorum so the cluster survives a master reboot. |
| **Tutorials (manim mp4)** | `./tutorial/render.sh` (needs ffmpeg) | renders into the Tutorial tab. |

---

## 8. First login (do this immediately)
1. Open `https://satyameba.local/` (accept the self-signed cert warning, or use a
   real cert via `issue_cert.sh` / Cloudflare).
2. Log in with `SAT_BOOTSTRAP_ADMIN_USERNAME` / `SAT_BOOTSTRAP_ADMIN_PASSWORD` from
   `.env`.
3. **Change the admin password.** If you'll expose the site publicly, enable admin
   2FA (`SAT_REQUIRE_ADMIN_2FA=true`) and enrol TOTP.
4. The **owner** account is separate (the break-glass identity); change its password too.

---

## 9. Adding / managing users (once live)
From **Admin** in the dashboard you can: send invites, bulk-create users, set
expiry dates and **GPU-hours quotas**, tag users, see the attention dashboard,
broadcast announcements, and flip **maintenance mode**. Users land in their own
Jupyter notebook with the shared folder mounted; GPU access is governed by the
scheduler in §6.

---

## 10. Day-2 operations
| Task | Command |
|------|---------|
| Backup (DB + secrets + user data) | `./scripts/backup.sh` |
| Restore | `./scripts/restore.sh <backup>` |
| DB migrations (auto-run at startup; manual control) | `./scripts/migrate.sh current` / `history` / `downgrade -1` |
| Reclaim disk now | `./scripts/cleanup.sh` |
| Verify GPU plumbing | `./scripts/verify_gpu.sh` |
| Verify DB | `./scripts/verify_db.sh` |
| Redeploy after an `.env` change | `docker stack deploy -c docker-compose.swarm.yml satyameba` |

---

## 11. Verify the whole thing is healthy
```bash
docker node ls                        # every node Ready / Active
docker stack services satyameba       # every service N/N replicas
curl -k https://<master>/healthz      # gateway OK
./scripts/verify_gpu.sh               # GPUs visible to scheduler
```
In the dashboard, **Admin → Nodes** should list every desktop as **online**
(heartbeats every 30s).

---

## 12. Troubleshooting — so nothing breaks

**Install "stuck" at `.env: line 4: Mukherjee: command not found`**
Old scripts `source`d `.env` and a value with a space broke it. **Fixed** —
`scripts/load_env.sh` now loads `.env` safely and `gen_secrets.sh` quotes the
owner. If you hit it on an old checkout: `git pull` then re-run, or quote the
line: `sed -i 's/^SAT_OWNER=Samaraho Mukherjee/SAT_OWNER="Samaraho Mukherjee"/' .env`.

**A worker won't join** — check the master IP, that `:2377` is reachable on the
VLAN, and that the join token is current (`docker swarm join-token -q worker` on
the master regenerates the command).

**GPU notebooks won't start on a node** — confirm the node is labelled
(`docker node ls` → `docker node inspect <id>` shows `satyameba.gpu=true`), the
NVIDIA toolkit is installed (`nvidia-ctk --version`), and run `./scripts/verify_gpu.sh`.

**Node shows offline** — the heartbeat timer isn't running:
`systemctl status satyameba-heartbeat.timer` on the worker.

**Browser cert warning** — expected with the self-signed cert. Issue a real one
(`./scripts/issue_cert.sh`) or front it with Cloudflare Tunnel.

**Re-running is safe** — `gen_secrets.sh`, `master_init.sh`, `worker_join.sh`, and
`cluster_setup.sh` are all idempotent. They won't clobber an existing `.env` or
secrets unless you pass `--force`.

---

*Owner: Samaraho Mukherjee. Only ports 80/443 are exposed. Read
`owner-setup/README.md` for the break-glass model and `docs/SECURITY.md` for the
threat model.*
