# SATYAMEBA — Characteristics, Limits & Everything You Need to Know

A single reference for what the platform does, how it behaves, and where its
edges are. Pair with `docs/SECURITY.md` and `docs/KNOWN_ISSUES.md`.

## What it is

A self-hosted, Colab-style multi-user notebook cloud for a small GPU lab.
Users register → an admin approves → they log in → they launch an **isolated**
JupyterLab that Docker Swarm schedules onto an available node. Everything runs
in Docker (backend, frontend, db, hub, monitoring, and the notebooks themselves).

## Capabilities

- Account registration with **admin approval gating**; admins can approve,
  reject, suspend (kick off), and reinstate users.
- One isolated JupyterLab per user (full Lab: write/import notebooks, terminal,
  upload, plots). Work persists in a private per-user volume.
- **Resource profiles** chosen at launch (payload-aware scheduling).
- **Shared dataset volume** mounted into every notebook at `/home/jovyan/shared`.
- Live **monitoring**: per-node CPU/GPU/network/storage via Prometheus + Grafana,
  plus inline cluster numbers pulled straight from Prometheus into the admin UI.
- **Single sign-on** from the SPA into JupyterHub (no second login).
- **Tamper-evident audit log** of every privileged action.
- Self-service **password change**.
- One-command **storage/resource scan** that sizes the deployment to the host.
- **Dynamic GPU load balancing**: whole node each while quiet, concurrent GPU
  sharing when busy, admin-approved **multi-GPU boost** for one session (see
  *Scaling* below).
- **Neon-themed JupyterLab** (animated gradient borders) with live RAM/VRAM/GPU/
  CPU widgets and an in-Lab **traffic strip** (node-busy light, "N sharing", a
  "More GPUs" button) — plus a matching neon SPA.
- **In-app notifications** (sharing started, boost approved/denied, node freed).
- **Maintainability**: add nodes any time; **remote/off-VLAN nodes** join over a
  Tailscale tailnet (a separate wizard); admin **drain/maintenance mode** per node.
- **Headless option**: uninstall the desktop to save RAM (reversible) and run a
  **curses console dashboard** (any resolution) on the monitors; everything as
  **systemd boot services**; a **one-button TUI setup wizard** (`setup/wizard.sh`)
  and an **all-in-one installer** (`setup/install_wizard.sh`).
- **Alembic-managed schema**: the gateway auto-migrates at startup
  (multi-replica-safe), adopts a pre-Alembic DB, and CI guards against drift —
  safe in-place upgrades, no `create_all` blindness (`scripts/migrate.sh`).

## Resource profiles (per notebook)

| Profile | RAM | CPU | GPU | Use |
|---------|-----|-----|-----|-----|
| Small   | 2 GB | 1 | 0 | light / teaching |
| Medium  | `SAT_MEM_LIMIT` (scanned, default 4 GB) | `SAT_CPU_LIMIT` (default 2) | 0 | default |
| Large   | 8 GB | 4 | 0 | heavier CPU jobs |
| GPU     | 8 GB | 4 | 1 | training/inference |

These are **reservations**: Swarm places work by the requested footprint. The
"Medium" RAM/CPU defaults are auto-set by `scripts/scan_resources.sh`.

## Storage behavior

- **Scan**: `scripts/scan_resources.sh` reads total/free disk on the Docker data
  root (plus RAM/cores) and writes `SAT_TOTAL_STORAGE_GB`, `SAT_FREE_STORAGE_GB`,
  a per-user share `SAT_USER_STORAGE_LIMIT_GB`, and per-notebook `SAT_MEM_LIMIT`
  / `SAT_CPU_LIMIT` into `.env`. Re-run after adding disks/RAM.
- **No upload cap**: the edge streams uploads with no size limit.
- **Per-user volume**: `satyameba-user-<username>` → `/home/jovyan/work`.
- **Shared volume**: `satyameba-shared` → `/home/jovyan/shared`.
- **Storage mode** (`SAT_USER_STORAGE_MODE`): `volume` = node-local (single host
  default); `host` = NFS path identical on every node so a user's work **follows
  them across nodes** (enable with `--nfs` / `setup_nfs.sh`). Use `host` for any
  real multi-node deployment.
- **Backup/restore**: `scripts/backup.sh` (Postgres dump + `.env`/secrets) and
  `scripts/restore.sh`.
- **Quota enforcement is OFF by default.** `SAT_USER_STORAGE_LIMIT_GB` is an
  *advisory* allocation. Hard per-volume quotas (`SAT_STORAGE_QUOTA_ENFORCE=true`)
  require an XFS prjquota-enabled Docker storage driver; otherwise storage is
  shared and best-effort. **Limit:** a user can fill the disk unless you enable
  prjquota or put volumes on a sized filesystem.

## Networking & ports

- **Only 80/443 are published** (the nginx edge). HTTP redirects to HTTPS.
- Internal services (gateway, hub, db, redis, prometheus, grafana, exporters)
  are not exposed to clients.
- Swarm ports `2377/tcp`, `7946/tcp+udp`, `4789/udp` must be open **VLAN-only**.
- Default TLS is **self-signed** (browser warning) → use `scripts/issue_cert.sh`
  for a real cert.

## Security characteristics (summary; full mapping in SECURITY.md)

- bcrypt passwords; **RS256** short-lived (15 min) access tokens; refresh-token
  rotation; session revocation on suspend/password-change.
- **Per-request HMAC signing** (timestamp + nonce) → tamper + replay protection
  on mutations. *Does not* hide a user's own Burp-proxied session — impossible in
  a browser; authorization is enforced server-side.
- ORM-only DB access (no SQLi), strict input validation, security headers, rate
  limiting (Redis-shared), best-effort bot filtering.
- Client JS can be obfuscated (`make obfuscate`) — **cosmetic only**, never a
  security boundary.
- **Un-removable Owner role** (the project owner) + an out-of-band **Tailscale
  break-glass tunnel** and **tamper response** (seal → armed/grace → crypto-erase)
  in `owner-setup/` — a control plane separate from the app. See
  [`../owner-setup/README.md`](../owner-setup/README.md).
- **Private per-account storage**: folders named `u-<hash-of-immutable-id>`, strict
  `0700`; a reused username can't inherit a deleted account's files.
- **At-rest encryption (gocryptfs)**: with `SAT_USER_ENCRYPTION=gocryptfs`, the
  disk only ever holds **ciphertext** (per-user keys derived from the owner KEK);
  a host-side agent mounts the decrypted view only into the running notebook. A
  stolen/pulled/decommissioned disk is unreadable; the owner crypto-erase
  (shred the KEK) makes everything permanently unrecoverable instantly.
  **Limit:** while a notebook runs, its view is decrypted (root on that node can
  read *live* data) — it protects data **at rest**, not in use.
- **Session-end teardown**: logout stops the notebook; idle-culler at 20 min.
- **TOTP 2FA** (per-user, optionally mandatory for admins) and forced rotation of
  the seeded admin/owner password.
- Notebook isolation: `cap_drop=ALL`, `no-new-privileges`, CPU/RAM caps, private
  volume, no host bind mounts, idle-culled. Optional **gVisor** runtime
  (`SAT_SANDBOX_RUNTIME=runsc`) for container-escape defense.
- Strict **CSP** + security headers on the SPA at the edge.

## Scaling & GPU load balancing (dynamic)

The gateway's own scheduler (`gateway/app/scheduler.py`) decides placement so it
can give people a whole node when it's quiet and fall back to sharing when busy.
Let **N** = online GPU nodes (read live from the Node table — *not* hardcoded, so
adding nodes just raises N) and **A** = active notebook users:

- **A ≤ N → exclusive whole node.** The launch is pinned to an empty node and
  reserves its GPU, so the user has the entire card/VRAM to themselves.
- **A > N → concurrent sharing.** All nodes are occupied, so the newcomer lands
  on the least-loaded node and **shares its GPU concurrently** (no Swarm GPU
  reservation + `NVIDIA_VISIBLE_DEVICES=all`; both kernels run at once — a
  "hello world" sips nothing, a training job uses what's free). Co-tenants get an
  in-app **notification** that they're now sharing, and the newcomer is **queued**
  for promotion to a dedicated node when one frees (promotion is opt-in via a
  restart so a running kernel is never killed).
- **Admin-approved boost → multi-GPU, Kaggle-style.** A user requests "more
  GPUs"; an admin approves; the next launch spreads across every GPU node that is
  **free** right now (the whole cluster at 3 a.m.). The grant is good for **one
  session**, then it's spent. `satyameba-ddp your_script.py` wraps `torchrun`
  with the injected rendezvous for distributed training.
- **API**: 2 gateway replicas behind the edge/routing mesh.
- **Live visibility**: per-user RAM/VRAM/GPU/CPU meters + a node-busy light and
  "N sharing" indicator in both the SPA workspace and the in-Lab traffic strip.
- **Honest limits**: sharing is cooperative concurrency (no hard VRAM caps — the
  RTX 5070 is consumer Blackwell, so **no MIG**). Cross-node multi-GPU needs
  DDP-aware code. The Swarm GPU sharing path (reserve vs. `NVIDIA_VISIBLE_DEVICES`
  + `default-runtime=nvidia`) should be validated on real hardware. Not
  autoscaling; not payload inspection.

## Availability limits (important)

- Swarm can run **3 managers** for quorum (`scripts/promote_managers.sh`) and the
  control-plane services tolerate a manager loss. The **database** is the
  remaining SPOF: the bundled Postgres is single-instance. Point
  `SAT_DATABASE_URL` at an HA Postgres + deploy with
  `docker-compose.external-db.yml` for full HA — you bring the replicated
  Postgres (not auto-provisioned).
- `--single` (compose) mode runs everything, including all notebooks, on one box.

## Defaults & key settings (`.env`)

| Setting | Default | Meaning |
|---------|---------|---------|
| `SAT_ACCESS_TOKEN_TTL_SECONDS` | 900 | access-token lifetime |
| `SAT_REFRESH_TOKEN_TTL_SECONDS` | 604800 | refresh/session lifetime |
| `SAT_RATE_LIMIT_PER_MINUTE` / auth | 120 / 10 | per-IP request budgets |
| `SAT_EXPECTED_USERS` | scanned (8) | planning denominator |
| `SAT_MEM_LIMIT` / `SAT_CPU_LIMIT` | scanned | medium-profile reservation |
| `SAT_GPU_ENABLED` / `SAT_GPU_RESOURCE` | false / gpu | GPU scheduling |
| `SAT_STORAGE_QUOTA_ENFORCE` | false | hard per-user disk quota (needs prjquota) |
| `SAT_REDIS_URL` | redis://redis:6379/0 | shared limiter/replay store |
| login lockout | 5 fails → 15 min | brute-force lockout |
| idle culler | 60 min | reclaim idle notebooks |

## Requirements

- Debian nodes with Docker CE + Compose v2 (installed by the wizard).
- For GPU: NVIDIA driver + Container Toolkit (wizard installs/verifies). **RTX
  5070 may need a 555+ driver from NVIDIA's CUDA repo.**
- Same-VLAN connectivity between nodes; SSH between them is convenient but not
  required.

## Honest non-goals / things it is NOT

- Not a hardened public-internet SaaS — it's a lab tool behind a VLAN.
- Not multi-region / HA-database out of the box.
- Not protected against a malicious *approved* user escaping the container kernel
  (add gVisor/Kata) or exhausting un-quota'd disk (enable prjquota).
- Client-side "encryption"/bot-blocking are deterrents, not guarantees.
