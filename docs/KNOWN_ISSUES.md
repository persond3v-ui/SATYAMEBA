# SATYAMEBA — Issue Log & Status

Self-audited list of flaws found in the Phase-1 core and their current status.
Severity: 🔴 high · 🟠 medium · 🟡 low. Status: ✅ fixed · 🟢 mitigated · 📌 documented.

## Resolved — security-hardening round

- **S-1 ✅ TOTP two-factor auth** — enrol/enable/disable endpoints + QR, login
  enforces the code when enabled (`SAT_REQUIRE_ADMIN_2FA` to mandate for admins).
- **S-2 ✅ Forced password rotation** — bootstrap admin flagged
  `must_change_password`; SPA banner + change-password clears it and revokes
  other sessions.
- **S-3 ✅ gVisor sandbox runtime option** — `scripts/setup_gvisor.sh` +
  `SAT_SANDBOX_RUNTIME=runsc` runs notebooks under gVisor (container-escape
  defense). Verify on hardware; GPU + gVisor has limitations.
- **S-4 ✅ CSP + header hardening on the SPA**, and the SSO one-time-token URL is
  no longer written to the access log.
- **S-5 📌 OIDC/LDAP** — still deferred; needs your IdP. Integration point noted
  in SECURITY.md.

## Resolved — production-readiness round

- **N-1 🔴 ✅ Per-user work was node-local in Swarm (data loss across nodes).**
  New `host`/NFS storage mode: `scripts/setup_nfs.sh` exports `/srv/satyameba`
  and mounts it on every node; the Hub pre-creates per-user dirs (owned by the
  notebook UID) so `/home/jovyan/work` and `/home/jovyan/shared` follow users
  wherever Swarm places them. Wired via `--nfs` / `--nfs-server`.

- **I-6 🔴 ✅→🟢 Master SPOF reduced.** `scripts/promote_managers.sh` for
  3-manager quorum + `docker-compose.external-db.yml` to run against an external
  HA Postgres. Residual: you must supply the replicated Postgres (documented).

- **N-2 🟠 ✅ Backup/restore.** `scripts/backup.sh` (pg_dump + env/secrets) and
  `scripts/restore.sh`.

- **N-3 🟠 ✅ Unbounded `sso_tokens`/sessions.** A maintenance loop
  (`maintenance.py`, started by the app lifespan) purges used/expired SSO tokens
  and dead sessions every 15 min.

- **N-4 🟡 ✅ SSO open redirect.** The login handler now rejects non-relative
  `next` targets.

- **N-5 🟡 ✅ Slow `metrics_live`.** Prometheus queries now run concurrently
  (`asyncio.gather`, 2 s timeout).

- **N-6 🟡 ✅ Dead metric.** Real request metrics + latency histogram via
  `MetricsMiddleware`; `/metrics` now reflects live traffic.

- **N-7 🟡 ✅ Friendly launch error + lifespan.** Launch returns 502 (not 500)
  when the Hub is down; startup migrated off the deprecated `on_event`.

## Resolved — first round

- **I-1 🔴 ✅ No SSO to JupyterHub (double login).**
  The gateway now mints a single-use, short-lived SSO token on launch
  (`SsoToken` table) and returns a `/hub/sso-login?token=...` URL. A new
  `SSOLoginHandler` in the authenticator redeems it via
  `/api/internal/redeem-ott` and logs the browser straight into JupyterLab — no
  second login.

- **I-2 🟠 ✅ JupyterLab iframe embedding.**
  The SPA now opens the notebook in a **new tab** (`window.open`), sidestepping
  frame-ancestors entirely; the Hub also sets a same-origin CSP as defense in
  depth.

- **I-3 🟠 ✅ 64 MB upload cap removed.**
  `client_max_body_size 0` + `proxy_request_buffering off` at the edge: dataset
  uploads stream through with no size limit.

- **I-4 🟠 ✅ Admin dashboard pulls live numbers from Prometheus.**
  New `/api/admin/metrics/live` proxies an allow-list of PromQL queries; the
  admin **Overview** shows CPU / RAM / disk / GPU / network / targets-up, polled
  every 10 s, in addition to the embedded Grafana tab.

- **I-5 🔴 ✅ Grafana no longer anonymous.**
  `GF_AUTH_ANONYMOUS_ENABLED=false` + `GF_USERS_ALLOW_SIGN_UP=false`; the
  dashboards require a Grafana login (admin password in `.env`).

- **I-7 🟠 ✅ Shared rate-limit + replay store.**
  New `ratestore.py` backs both the rate limiter and the replay-nonce check with
  Redis when `SAT_REDIS_URL` is set (a `redis` service is in both stacks), so
  limits and replay protection hold across gateway replicas. In-process fallback
  for single-replica.

- **I-8 🔴 ✅ Notebook image is built.**
  A `notebook-image` builder service + `make up`/`make build`/`make
  notebook-image` build `satyameba/notebook:latest` so the first launch spawns.

- **I-9 🟠 ✅ GPU advertised to Swarm.**
  `scripts/setup_gpu_runtime.sh` writes `node-generic-resources` (GPU UUIDs) into
  `daemon.json` and enables `swarm-resource` in the nvidia runtime; called
  automatically by `master_init.sh`/`worker_join.sh` on GPU nodes.

- **I-11 🟠 ✅ Payload-aware scheduling via profiles.**
  Users pick Small / Medium / Large / GPU at launch; the gateway passes it as a
  spawn option and a `pre_spawn_hook` reserves the matching CPU/RAM/GPU, so Swarm
  distributes by the requested footprint.

- **I-13 🟠 ✅ Shared dataset volume.**
  Every notebook mounts `satyameba-shared` at `/home/jovyan/shared`
  (`SAT_SHARED_VOLUME` / `SAT_SHARED_MODE`). *Multi-node note below.*

- **I-14 🟠 ✅ SwarmSpawner resource spec corrected.**
  Resources are set via `mem_limit`/`cpu_limit` traits plus `generic_resources`
  for GPUs through the `pre_spawn_hook`.

- **I-15 🟡 ✅ Tests + CI.**
  `gateway/tests/` covers onboarding, request signing (replay/tamper), SSO OTT,
  change-password, suspend, and audit-chain integrity. `.github/workflows/ci.yml`
  runs the suite, the client/server HMAC parity check, and compose validation.

- **I-16 🟡 ✅ Self-service password change.**
  `POST /api/auth/change-password` (revokes other sessions) + a form in the
  workspace, so the bootstrap admin password can be rotated on first login.

- **I-10 🟡 ✅ Real TLS path.** `scripts/issue_cert.sh` issues a Let's Encrypt
  cert via the wired ACME webroot; self-signed remains the zero-config default.

## Mitigated / documented (need real hardware or infra to fully close)

- **I-6 🔴 🟢 Master single point of failure.**
  Control-plane is pinned to managers and the gateway runs 2 replicas, but a
  single-manager lab still has the DB/edge as a SPOF. `docs/DEPLOYMENT.md` now
  documents promoting 3 managers for quorum and Postgres replication. Full HA
  (replicated Postgres) is not shipped yet — **the honest residual limitation.**

- **I-12 🟡 📌 Single-host mode does not distribute.** By design: `--single`
  runs every notebook on one box. Use Swarm for multi-node load balancing.

- **I-13 (multi-node) 🟠 📌 Shared volume is node-local.** The shared volume is a
  local Docker volume; across nodes it needs an NFS/object-store backing. Steps
  are in `docs/DEPLOYMENT.md`.

- **GPU swarm runtime** (I-9/I-14): implemented per NVIDIA's documented setup but
  **not yet verified on physical RTX 5070 hardware** — validate `nvidia-smi`
  inside a spawned GPU notebook after deploying.

---
*See `docs/CHARACTERISTICS.md` for the full list of capabilities, limits, and
defaults.*
