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
- Notebook isolation: `cap_drop=ALL`, `no-new-privileges`, CPU/RAM caps, private
  volume, no host bind mounts, idle-culled. *Not* hardened against kernel
  container-escape — add gVisor/Kata for hostile multi-tenancy.

## Scaling & load balancing

- **Notebooks**: each launch is a Swarm service; the scheduler spreads by task
  count honoring the profile's reservation, and constrains GPU work to
  `satyameba.gpu==true` nodes. *Example:* 16 users on 4 nodes ≈ 4 notebooks/node
  (RAM permitting); GPU notebooks capped by physical GPUs.
- **API**: 2 gateway replicas behind the edge/routing mesh.
- **Not** autoscaling, **not** true payload inspection, **no** GPU time-slicing
  (one notebook reserves a whole GPU).

## Availability limits (important)

- A **single-manager** deployment has the database and edge as a **single point
  of failure** — if the master dies, the platform is down. Workers add notebook
  compute redundancy only. For resilience, run **3 managers** (quorum) and
  replicate Postgres (see DEPLOYMENT.md). Replicated Postgres is **not shipped**.
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
